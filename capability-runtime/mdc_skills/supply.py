"""Recursive observed material goals: collect -> tools -> station -> production.

All target counts are totals in actual inventory, making re-entry a fresh goal
check rather than a replayed action sequence. Unknown mutations never retry;
partial occupied crafting/machine state remains an explicit intervention gate.
"""
from collections import Counter
from dataclasses import dataclass
from contextlib import contextmanager
import math
from .core import Outcome, SkillError, require
from . import inventory, planning, production, reach, resources, mobility

SMELT_OUTPUTS = {
    'minecraft:iron_ingot': ('minecraft:raw_iron',),
    'minecraft:copper_ingot': ('minecraft:raw_copper',),
    'minecraft:gold_ingot': ('minecraft:raw_gold',),
    'minecraft:stone': ('minecraft:cobblestone',),
    'minecraft:smooth_stone': ('minecraft:stone',),
    'minecraft:glass': ('minecraft:sand',),
    'minecraft:smooth_sandstone': ('minecraft:sandstone',),
    'minecraft:smooth_quartz': ('minecraft:quartz_block',),
    'minecraft:brick': ('minecraft:clay_ball',),
    'minecraft:nether_brick': ('minecraft:netherrack',),
    'minecraft:charcoal': tuple('minecraft:' + w + '_log' for w in ('oak','spruce','birch','jungle','acacia','dark_oak','mangrove','cherry')),
}
# Narrow, validated reverse routing for the eight existing food recipes. This
# deliberately adds no raw-food acquisition/hunting policy.
FOOD_SMELT_OUTPUTS = {
    recipe.output_id: (source,)
    for source, recipe in production.SMELTING_RECIPES.items()
    if 'minecraft:smoker' in recipe.stations
}
assert len(FOOD_SMELT_OUTPUTS) == 8
assert not (set(FOOD_SMELT_OUTPUTS) & set(SMELT_OUTPUTS))
SMELT_OUTPUTS.update(FOOD_SMELT_OUTPUTS)

MINING_TOOLS = {
    'minecraft:cobblestone': 'minecraft:wooden_pickaxe',
    'minecraft:cobbled_deepslate': 'minecraft:wooden_pickaxe',
    'minecraft:coal': 'minecraft:wooden_pickaxe',
    'minecraft:raw_iron': 'minecraft:stone_pickaxe',
    'minecraft:raw_copper': 'minecraft:stone_pickaxe',
    'minecraft:raw_gold': 'minecraft:iron_pickaxe',
}
TIER = {'wooden':0,'golden':0,'stone':1,'iron':2,'diamond':3,'netherite':4}


def _counts(observation):
    out = Counter()
    for row in inventory.items(observation):
        require(type(row.get('count')) is int and row['count'] >= 0, 'invalid_inventory_count')
        out[row['id']] += row['count']
    return +out


def _clean_cursor(observation):
    menu=observation.state.get('menu',{})
    require(menu.get('carried',{}).get('empty') is True and menu.get('slots_truncated') is False,
            'supply_requires_complete_menu_and_empty_cursor')


def _exclusions(positions):
    require(isinstance(positions,(list,tuple,set,frozenset)) and len(positions)<=32768,
            'bounded_excluded_positions_required')
    return frozenset(tuple(reach.coordinate(p)[k] for k in ('x','y','z')) for p in positions)


def place_workstation(runtime, block_id, *, position=None, excluded_positions=()):
    """Place one owned station in a fresh, clear, supported local cell.

    Orientation is deliberately unconstrained for this semantic station goal;
    native exact source/support/target binding and observed material consumption
    remain mandatory. The oriented building executor has a stronger state goal.
    """
    require(block_id in production.STATIONS, 'unsupported_workstation')
    excluded=_exclusions(excluded_positions)
    selected=inventory.ensure_hotbar(runtime,block_id)
    runtime.require_success(selected)
    before=runtime.observe(terrain=True, radius=4, vertical=3)
    _clean_cursor(before)
    require(before.state.get('screen_open') is False, 'close_existing_menu_before_station_placement')
    feet={k:math.floor(before.player[k]) for k in ('x','y','z')}
    nearby=before.state.get('nearby',{})
    require(nearby.get('truncated') is False and isinstance(nearby.get('entities'),list), 'complete_local_entities_required')
    # Prefer one of the four ordinary adjacent cells; no excavation or terrain alteration.
    candidates=[reach.coordinate(position)] if position is not None else [
        {'x':feet['x']+dx,'y':feet['y'],'z':feet['z']+dz} for dx,dz in ((1,0),(-1,0),(0,1),(0,-1))]
    chosen=None
    for target in candidates:
        if tuple(target[k] for k in ('x','y','z')) in excluded:continue
        support={**target,'y':target['y']-1}
        try:
            destination=reach.block_at(before,target);floor=reach.block_at(before,support)
            head=reach.block_at(before,{**target,'y':target['y']+1})
        except SkillError:
            continue
        if (destination['id'] not in resources.AIR or head['id'] not in resources.AIR
                or floor.get('full_top_support') is not True or floor.get('collision_known') is not True
                or floor.get('fluid')!='minecraft:empty' or floor.get('hazards')!=[]):continue
        if target['x']==feet['x'] and target['z']==feet['z']:continue
        occupied=False
        for entity in nearby['entities']:
            box=entity.get('bounding_box',{})
            low,high=box.get('min'),box.get('max')
            require(isinstance(low,dict) and isinstance(high,dict), 'entity_bounds_required_for_station_placement')
            if all(high[k]>target[k] and low[k]<target[k]+1 for k in ('x','y','z')):occupied=True
        if not occupied:
            chosen=(target,support,destination,floor);break
    require(chosen is not None,'no_clear_supported_station_cell')
    target,support,destination,floor=chosen
    wanted=_counts(before);wanted[block_id]-=1;wanted=+wanted
    command={'op':'action','action':'place_block','support':support,'face':'up',
        'hotbar_slot':before.player['selected_slot'],'sneak':True,'jump':False,'timeout_ms':5000,
        'expected_support_id':floor['id'],'expected_support_properties':floor['properties'],
        'expected_target_id':destination['id'],'expected_target_properties':destination['properties'],
        'expected_block_id':block_id,'expected_block_properties':{}}
    def verified(_,after):
        return reach.block_at(after,target)['id']==block_id and _counts(after)==wanted
    outcome=runtime.execute('supply.place_workstation',command,verified,before=before)
    if not outcome.ok:return outcome
    return Outcome(outcome.status,outcome.reason,tuple(selected.request_ids)+outcome.request_ids,
        {**outcome.evidence,'station':{'position':target,'block_id':block_id,'face':'up'}},outcome.last_observation)


@dataclass
class _Budget:
    nodes: int
    blocks: int
    batches: int
    deadline: float
    ids: list
    observations: list

    def check(self,runtime):
        require(runtime.clock()<self.deadline,'supply_deadline_exceeded')
        require(self.nodes>0,'supply_dependency_budget_exhausted')
        self.nodes-=1

    def accept(self,runtime,result):
        self.ids.extend(result.request_ids)
        value=runtime.require_success(result)
        if value is not None:self.observations.append(value)
        return value


class _DeadlineRuntime:
    """Enforce the original goal admission deadline inside every nested helper."""
    def __init__(self, runtime, deadline, max_actions):
        self._runtime, self.deadline = runtime, deadline
        self.remaining = max_actions
        self.last_clock = runtime.clock()

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def check(self):
        now = self._runtime.clock()
        require(now >= self.last_clock, 'supply_clock_regressed')
        self.last_clock = now
        require(now < self.deadline, 'supply_deadline_exceeded')
        return self.deadline - now

    def observe(self, *args, **kwargs):
        self.check()
        result = self._runtime.observe(*args, **kwargs)
        self.check()
        return result

    def execute(self, skill, command, verify, **kwargs):
        left = self.check()
        require(self.remaining > 0, 'supply_action_budget_exhausted')
        require(left >= .05, 'supply_deadline_exceeded')
        self.remaining -= 1
        body = dict(command)
        body['timeout_ms'] = min(body.get('timeout_ms', 15000), int(left * 1000), 60000)
        outcome = self._runtime.execute(skill, body, verify, **kwargs)
        # A known terminal outcome is retained even when it arrives after the
        # deadline. No later mutation may be admitted under this goal.
        return outcome

    def sleeper(self, seconds):
        left = self.check()
        self._runtime.sleeper(min(seconds, left))
        self.check()

    def result(self, *args, **kwargs):
        self.check()
        return self._runtime.result(*args, **kwargs)


class MaterialGoals:
    def __init__(self,runtime,*,max_nodes=128,max_blocks=64,max_batches=128,timeout_seconds=600,max_actions=4096,max_search_steps=64,max_walk_distance=512,excluded_positions=()):
        require(all(type(x) is int and 1<=x<=1024 for x in (max_nodes,max_blocks,max_batches)),'invalid_supply_budgets')
        require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 1<=timeout_seconds<=3600,
                'invalid_supply_deadline')
        require(type(max_actions) is int and 1<=max_actions<=32768,'invalid_supply_action_budget')
        deadline=runtime.clock()+timeout_seconds
        self.runtime=_DeadlineRuntime(runtime,deadline,max_actions)
        self.budget=_Budget(max_nodes,max_blocks,max_batches,deadline,[],[])
        self.stack=[]
        self.protected=Counter()
        self.reservations=Counter()
        require(type(max_search_steps)is int and 0<=max_search_steps<=512 and type(max_walk_distance)is int
                and 0<=max_walk_distance<=8192,'invalid_supply_search_budget')
        self.search_steps=max_search_steps
        self.walk_distance=max_walk_distance
        self.visited=set()
        self.stations={}
        self.excluded=_exclusions(excluded_positions)
        self.excluded_json=[dict(zip(('x','y','z'),p)) for p in sorted(self.excluded)]

    @contextmanager
    def reserve(self, consumables):
        self.reservations.update(consumables)
        try:
            for item in consumables:
                self.ensure(item,self.protected[item]+self.reservations[item])
            yield
        finally:
            self.reservations.subtract(consumables)
            self.reservations=+self.reservations

    def observe(self,terrain=False):
        self.budget.check(self.runtime)
        value=self.runtime.observe(terrain=terrain,allow_menu=True)
        _clean_cursor(value)
        self.budget.observations.append(value)
        return value

    def close_menu(self):
        value=self.observe()
        if value.state.get('screen_open') is True:
            self.budget.accept(self.runtime,reach.close_menu(self.runtime))

    def choose(self,alternatives,needed):
        observation=self.observe(terrain=False);counts=_counts(observation)
        available=[item for item in alternatives if counts[item]>=needed]
        if available:return max(available,key=lambda item:counts[item])
        # Recipe alternatives are grounded in current inventory and a fresh local
        # resource scan; ties use the explicit vanilla recipe order.
        self.close_menu()
        observation=self.observe(terrain=True)
        blocks=Counter(c.get('id') for c in observation.terrain.get('cells',[]) if c.get('status')=='loaded' and c.get('known') is True)
        def supply_score(item):
            score=counts[item]*100
            if item.endswith('_planks'):
                stem=item.removesuffix('_planks')
                score+=counts[stem+'_log']*4+blocks[stem+'_log']*4
            for block in planning.RESOURCE_BLOCKS.get(item,()):score+=blocks[block]
            return score
        return max(alternatives,key=supply_score)

    def station(self,allowed):
        self.close_menu()
        cached=next((self.stations[i] for i in allowed if i in self.stations),None)
        if cached is not None:return cached
        discovery=planning.discover_workstations(self.runtime,station_ids=allowed)
        candidates=[row for row in discovery.evidence['stations']
            if tuple(row['position'][k] for k in ('x','y','z')) not in self.excluded]
        if candidates:
            selected=candidates[0]
            descriptor={k:selected[k] for k in ('position','block_id','face')}
            descriptor['approach_goal']=selected['approach']['goal']
            self.stations[descriptor['block_id']]=descriptor
            return descriptor
        wanted='minecraft:crafting_table' if 'minecraft:crafting_table' in allowed else 'minecraft:furnace'
        self.ensure(wanted,1+self.protected[wanted]+self.reservations[wanted])
        self.close_menu()
        result=place_workstation(self.runtime,wanted,excluded_positions=self.excluded_json)
        observation=self.budget.accept(self.runtime,result)
        descriptor=dict(result.evidence['station'])
        descriptor['approach_goal']={k:math.floor(observation.player[k]) for k in ('x','y','z')}
        self.stations[descriptor['block_id']]=descriptor
        return descriptor

    def approach_station(self,station):
        self.close_menu()
        self.budget.accept(self.runtime,mobility.navigate_loaded(self.runtime,station['approach_goal']))
        current=self.observe(terrain=True)
        require(reach.block_at(current,station['position'])['id']==station['block_id'],
                'known_workstation_changed_no_replacement')
        return {k:station[k] for k in ('position','block_id','face')}

    def search_resource(self,item_id):
        while True:
            observed=self.observe(terrain=True)
            feet={k:math.floor(observed.player[k]) for k in ('x','y','z')}
            cells=[c for c in observed.terrain.get('cells',[]) if c.get('id') in planning.RESOURCE_BLOCKS[item_id]
                and c.get('y',-10000)>=feet['y'] and (c.get('x'),c.get('z'))!=(feet['x'],feet['z'])
                and tuple(c.get(k) for k in ('x','y','z')) not in self.excluded]
            for cell in cells:
                exact=reach.block_at(observed,{k:cell[k] for k in ('x','y','z')})
                if planning._approach(observed,exact,self.runtime) is not None:return
            require(self.search_steps>0,'supply_loaded_resource_search_exhausted')
            grid,stamp=reach._grid(observed);grid.require_fresh(stamp,self.runtime.clock())
            start=reach.Block.parse(feet);paths=mobility.loaded_paths(grid,start,max_steps=16)
            self.visited.add(start)
            options=[p for p in paths if p not in self.visited and p!=start and len(paths[p])>2]
            require(options,'supply_no_unvisited_safe_loaded_frontier')
            # Breadth coverage is driven only by actually loaded safe cells.
            target=max(options,key=lambda p:(min(abs(p.x-start.x)+abs(p.z-start.z),4),-len(paths[p]),p.x,p.z))
            steps=len(paths[target])-1
            require(self.walk_distance>=steps,'supply_walk_budget_exhausted')
            self.search_steps-=1;self.walk_distance-=steps
            result=mobility.navigate_loaded(self.runtime,{'x':target.x,'y':target.y,'z':target.z},max_segments=1,max_steps=16)
            self.budget.accept(self.runtime,result)
            self.visited.update(paths[target])

    def mining_tool(self,item_id):
        required=MINING_TOOLS.get(item_id)
        if required is None:return
        rows=inventory.items(self.observe())
        min_tier=TIER[required.split(':')[-1].split('_')[0]]
        suitable=[r for r in rows if r.get('count',0)>0 and r['id'].endswith('_pickaxe')
            and TIER.get(r['id'].split(':')[-1].split('_')[0],-1)>=min_tier]
        if suitable:tool=max(suitable,key=lambda r:TIER.get(r['id'].split(':')[-1].split('_')[0],-1))['id']
        else:self.ensure(required,1);tool=required
        self.close_menu()
        self.budget.accept(self.runtime,inventory.ensure_hotbar(self.runtime,tool))

    def ensure(self,item_id,count):
        require(isinstance(item_id,str) and item_id.startswith('minecraft:') and type(count) is int and 1<=count<=2304,
                'bounded_item_total_required')
        self.budget.check(self.runtime)
        observation=self.observe()
        have=_counts(observation)[item_id]
        if have>=count:return
        require(item_id not in self.stack,'cyclic_material_dependency')
        self.stack.append(item_id)
        try:
            name=item_id.removeprefix('minecraft:')
            if name in production.CRAFT_RECIPES:
                recipe=production.CRAFT_RECIPES[name]
                batches=min(32,math.ceil((count-have)/recipe.count),self.budget.batches)
                require(batches>0,'supply_crafting_budget_exhausted')
                needs_table=(len(recipe.pattern)>2 or max(map(len,recipe.pattern))>2
                    or name in production.BASE_RECIPES and name not in ('stick','torch','crafting_table'))
                # Bootstrap station dependencies first. A newly made station
                # must never consume ingredients reserved for the final recipe.
                station=self.station(('minecraft:crafting_table',)) if needs_table else None
                need=Counter(ch for row in recipe.pattern for ch in row if ch!=' ')
                ingredients={symbol:self.choose(recipe.ingredients[symbol],n*batches) for symbol,n in need.items()}
                consolidated=Counter()
                for symbol,n in need.items():consolidated[ingredients[symbol]]+=n*batches
                # The entire sibling bill stays reserved while any one
                # dependency is produced (sticks must not steal pickaxe planks).
                with self.reserve(consolidated):
                    if station is not None:station=self.approach_station(station)
                    self.budget.batches-=batches
                    result=production.craft(self.runtime,name,batches=batches,station=station,max_actions=1024,ingredients=ingredients)
                    self.budget.accept(self.runtime,result)
            elif item_id in SMELT_OUTPUTS:
                quantity=min(32,count-have)
                # A recipe is not a source: reject unavailable raw food before
                # choosing/bootstraping a station or closing the current menu.
                if item_id in FOOD_SMELT_OUTPUTS:
                    source=FOOD_SMELT_OUTPUTS[item_id][0]
                    require(_counts(observation)[source] >= quantity+self.protected[source]+self.reservations[source],
                            'unsupported_food_source:'+source+';required_carried_raw='+str(quantity+self.protected[source]+self.reservations[source]))
                else:
                    source=self.choose(SMELT_OUTPUTS[item_id],quantity)
                station=self.station(production.SMELTING_RECIPES[source].stations)
                self.ensure(source,quantity+self.protected[source])
                # Prefer already available fuel; otherwise make a concrete small
                # plank fuel batch from observed wood. No imaginary fuel credit.
                fuel_observation=self.observe();counts=_counts(fuel_observation)
                fuel=next((x for x,ticks in production.FUELS.items() if counts[x]>=math.ceil(quantity*200/ticks)+self.protected[x]+(quantity if x==source else 0)),None)
                if fuel is None:
                    fuel=self.choose(tuple(x for x in production.FUELS if x.endswith('_planks')),math.ceil(quantity*200/300))
                fuel_count=math.ceil(quantity*production.SMELTING_RECIPES[source].furnace_ticks/production.FUELS[fuel])
                consumables=Counter({source:quantity});consumables[fuel]+=fuel_count
                with self.reserve(consumables):
                    station=self.approach_station(station)
                    self.budget.accept(self.runtime,production.smelt(self.runtime,source,count=quantity,fuel_id=fuel,station=station,
                        max_actions=1024,wait_seconds=min(600,max(15,quantity*12))))
            elif item_id in ('minecraft:ender_pearl','minecraft:blaze_rod','minecraft:gunpowder','minecraft:string'):
                from .combat_goals import acquire_mob_drops
                self.close_menu()
                search=min(32,self.search_steps);walk=min(256,self.walk_distance)
                self.search_steps-=search;self.walk_distance-=walk
                self.budget.accept(self.runtime,acquire_mob_drops(self.runtime,item_id,count=count,
                    max_targets=16,max_actions=min(256,self.runtime.remaining),
                    max_search_steps=search,max_walk_distance=walk,
                    timeout_seconds=max(1,min(600,self.budget.deadline-self.runtime.clock()))))
            elif item_id in planning.RESOURCE_BLOCKS:
                self.mining_tool(item_id)
                self.close_menu()
                self.search_resource(item_id)
                require(self.budget.blocks>0,'supply_resource_budget_exhausted')
                deficit=count-have
                allowance=min(self.budget.blocks,max(1,deficit),32)
                self.budget.blocks-=allowance
                self.budget.accept(self.runtime,planning.acquire_nearby(self.runtime,item_id,count=min(count,have+allowance),max_blocks=allowance,excluded_positions=self.excluded_json))
            else:
                raise SkillError('no_supported_acquisition_recipe_for_'+item_id)
        finally:self.stack.pop()
        after=self.observe()
        require(_counts(after)[item_id]>have,'material_goal_made_no_observed_progress')
        if _counts(after)[item_id]<count:self.ensure(item_id,count)


def ensure_items(runtime,requirements,*,max_nodes=128,max_blocks=64,max_batches=128,timeout_seconds=600,max_actions=4096,max_search_steps=64,max_walk_distance=512,excluded_positions=()):
    require(isinstance(requirements,dict) and 1<=len(requirements)<=32,'bounded_material_goals_required')
    goal=MaterialGoals(runtime,max_nodes=max_nodes,max_blocks=max_blocks,max_batches=max_batches,timeout_seconds=timeout_seconds,max_actions=max_actions,max_search_steps=max_search_steps,max_walk_distance=max_walk_distance,excluded_positions=excluded_positions)
    require(all(isinstance(item,str) and item.startswith('minecraft:') and type(count)is int and 1<=count<=2304
                for item,count in requirements.items()),'bounded_material_goals_required')
    goal.protected=Counter(requirements)
    for item_id,count in requirements.items():goal.ensure(item_id,count)
    final=goal.observe()
    counts=_counts(final)
    require(all(counts[item]>=n for item,n in requirements.items()),'final_material_totals_not_observed')
    outcome=goal.runtime.result('supply.ensure_items',goal.budget.observations,requirements=requirements,
        actual_totals={i:counts[i] for i in requirements},action_request_ids=goal.budget.ids)
    return Outcome(outcome.status,outcome.reason,tuple(dict.fromkeys(goal.budget.ids+list(outcome.request_ids))),outcome.evidence,outcome.last_observation)
