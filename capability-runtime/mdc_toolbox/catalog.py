"""Closed capability aggregation; source presence is never runtime acceptance."""
from __future__ import annotations
from copy import deepcopy
import importlib
from .contracts import API_VERSION, ToolboxError, validate_schema, obj

BASELINE_CAPABILITIES = [{'operation_id': 'build', 'group': 'building', 'source_relative': 'capability-runtime/mdc_skills/building.py', 'source_sha256': '9aeeb3629d765659feda19ccfc7eeb469db6084e123c821352355d48f3781d05', 'description': 'Execute imported exact full-cube or oriented blueprint with durable progress'}, {'operation_id': 'build_with_materials', 'group': 'building', 'source_relative': 'capability-runtime/mdc_skills/construction.py', 'source_sha256': 'b505b28207fa9e32b5d678a9c8b34854a34bc6502c043de00f312338ca0e97ac', 'description': 'Derive blueprint materials, procure outside protected worksite, return and execute verified construction'}, {'operation_id': 'defeat', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/threats.py', 'source_sha256': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'description': 'Bounded semantic attacks against an explicit hostile'}, {'operation_id': 'defeat_nearby', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/combat_goals.py', 'source_sha256': 'da85f844b3b732472c7cb8a953c77182315a219d92cf368ccd3717b64457f2be', 'description': 'Choose observed targets and execute species-specific bounded encounters'}, {'operation_id': 'deflect_shulker_bullet', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/expedition.py', 'source_sha256': 'cb001645efed63d7a7b115054162192c98c2eda5f39f131315646be8e656c219', 'description': 'One observed bullet interception with later removal proof'}, {'operation_id': 'discover_mobs', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/combat_goals.py', 'source_sha256': 'da85f844b3b732472c7cb8a953c77182315a219d92cf368ccd3717b64457f2be', 'description': 'Discover observed species and explicit risk prerequisites'}, {'operation_id': 'engage', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/threats.py', 'source_sha256': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'description': 'Bounded native combat against a supported observed hostile'}, {'operation_id': 'hunt_resource', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/combat_goals.py', 'source_sha256': 'da85f844b3b732472c7cb8a953c77182315a219d92cf368ccd3717b64457f2be', 'description': 'Acquire actual inventory totals from observed mob drops with bounded search'}, {'operation_id': 'recover_hazard', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/threats.py', 'source_sha256': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'description': 'Follow an observed environmental escape route'}, {'operation_id': 'retreat', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/threats.py', 'source_sha256': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'description': 'Execute a checked short retreat from an explicit threat'}, {'operation_id': 'strike', 'group': 'combat', 'source_relative': 'capability-runtime/mdc_skills/threats.py', 'source_sha256': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'description': 'One guarded attack with later health loss proof'}, {'operation_id': 'activate_end_portal', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Fill observed oriented frames and verify portal'}, {'operation_id': 'clear_observed_crystals', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Select and remove only safely actionable observed crystals'}, {'operation_id': 'discover_end_goals', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Read-only discovery of loaded End goals and blockers'}, {'operation_id': 'end_battle', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Bounded crystal/cage/perched-dragon sequence with actual evidence'}, {'operation_id': 'end_expedition', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/expedition.py', 'source_sha256': 'cb001645efed63d7a7b115054162192c98c2eda5f39f131315646be8e656c219', 'description': 'Discover and execute bounded dragon, gateway, outer-End and shulker-box phases'}, {'operation_id': 'enter_portal', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Enter an observed portal and prove expected dimension'}, {'operation_id': 'gateway_pearl', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'One ordinary pearl throw with expected loaded End-gateway landing proof'}, {'operation_id': 'ignite_nether_portal', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Ignite an observed valid portal frame'}, {'operation_id': 'open_crystal_cage', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Mine selected observed cage bars within reach'}, {'operation_id': 'remove_crystal', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Fire one guarded crystal shot and verify loaded-area removal'}, {'operation_id': 'wait_dragon_phase', 'group': 'dimensions_end', 'source_relative': 'capability-runtime/mdc_skills/dimensions.py', 'source_sha256': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'description': 'Read-only bounded safe dragon phase observation'}, {'operation_id': 'consume', 'group': 'inventory_equipment_use', 'source_relative': 'capability-runtime/mdc_skills/inventory.py', 'source_sha256': '4bd3f8e1c181d5cb83bd97bbcaffc5e1fadce9b0b978683a2d81ee765a95114d', 'description': 'Use food/potion/milk and verify semantic effect'}, {'operation_id': 'ensure_hotbar', 'group': 'inventory_equipment_use', 'source_relative': 'capability-runtime/mdc_skills/inventory.py', 'source_sha256': '4bd3f8e1c181d5cb83bd97bbcaffc5e1fadce9b0b978683a2d81ee765a95114d', 'description': 'Move/select the observed required stack'}, {'operation_id': 'equip', 'group': 'inventory_equipment_use', 'source_relative': 'capability-runtime/mdc_skills/inventory.py', 'source_sha256': '4bd3f8e1c181d5cb83bd97bbcaffc5e1fadce9b0b978683a2d81ee765a95114d', 'description': 'Equip through verified vanilla inventory slots'}, {'operation_id': 'select_hotbar', 'group': 'inventory_equipment_use', 'source_relative': 'capability-runtime/mdc_skills/inventory.py', 'source_sha256': '4bd3f8e1c181d5cb83bd97bbcaffc5e1fadce9b0b978683a2d81ee765a95114d', 'description': 'Select and verify an existing hotbar stack'}, {'operation_id': 'craft', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/production.py', 'source_sha256': '094d0c82544c9ad5eefa83cd602de9958ea2e394c5bb3a72e46dd5199affb749', 'description': 'Craft a supported shaped recipe with exact inventory evidence'}, {'operation_id': 'craft_nearby', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/planning.py', 'source_sha256': 'efaf5812ebc1ba82a62d0a97db5c957acd41f52fe598b5920c2c6e90b15280d4', 'description': 'Discover a station and carry out an explicit recipe'}, {'operation_id': 'discover_workstations', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/planning.py', 'source_sha256': 'efaf5812ebc1ba82a62d0a97db5c957acd41f52fe598b5920c2c6e90b15280d4', 'description': 'Select observed local stations and safe approach stands'}, {'operation_id': 'open_workstation', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/production.py', 'source_sha256': '094d0c82544c9ad5eefa83cd602de9958ea2e394c5bb3a72e46dd5199affb749', 'description': 'Open the observed vanilla station'}, {'operation_id': 'smelt', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/production.py', 'source_sha256': '094d0c82544c9ad5eefa83cd602de9958ea2e394c5bb3a72e46dd5199affb749', 'description': 'Load fuel/input, wait for actual smelting and collect output'}, {'operation_id': 'smelt_nearby', 'group': 'production', 'source_relative': 'capability-runtime/mdc_skills/planning.py', 'source_sha256': 'efaf5812ebc1ba82a62d0a97db5c957acd41f52fe598b5920c2c6e90b15280d4', 'description': 'Choose observed station/fuel and carry out smelting'}, {'operation_id': 'boat_dismount', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Dismount only onto verified dry supported ground'}, {'operation_id': 'boat_mount', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Mount the exact observed boat and verify vehicle identity'}, {'operation_id': 'boat_travel', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Continue bounded observed water segments and verify arrival'}, {'operation_id': 'bridge_step', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Sneak-place one verified edge block then move onto it'}, {'operation_id': 'close_menu', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/reach.py', 'source_sha256': '7bd0a61b3f9345f94ca2194ed00d4acf7c500f7ba71c1560c2c4e9aa56305aee', 'description': 'Close the exact current menu with empty cursor'}, {'operation_id': 'interact', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/reach.py', 'source_sha256': '7bd0a61b3f9345f94ca2194ed00d4acf7c500f7ba71c1560c2c4e9aa56305aee', 'description': 'Interact once with an observed visible block face'}, {'operation_id': 'navigate', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/reach.py', 'source_sha256': '7bd0a61b3f9345f94ca2194ed00d4acf7c500f7ba71c1560c2c4e9aa56305aee', 'description': 'Reach a bounded observed local goal'}, {'operation_id': 'navigate_loaded', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Replan bounded fresh loaded movement with ordinary one-block elevation changes'}, {'operation_id': 'pillar_down', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Mine one exact owned pillar step above observed support'}, {'operation_id': 'pillar_up', 'group': 'reach_interaction', 'source_relative': 'capability-runtime/mdc_skills/mobility.py', 'source_sha256': '5f3dd172e3aacbce7962d60293358f14fd8513621561e8dd2e697f745e2378e6', 'description': 'Place one owned full cube beneath a guarded jump'}, {'operation_id': 'acquire_nearby', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/planning.py', 'source_sha256': 'efaf5812ebc1ba82a62d0a97db5c957acd41f52fe598b5920c2c6e90b15280d4', 'description': 'Select local resource blocks/tools and prove inventory goal'}, {'operation_id': 'collect', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/resources.py', 'source_sha256': 'e510ed65fc43e561a141296a39606e45157c5ac0e2ededd132812cd299fbac3c', 'description': 'Approach actual drops and verify inventory gain'}, {'operation_id': 'ensure_items', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/supply.py', 'source_sha256': 'e1333aa2c3b5edad95aa700012a11f09bf05d2f064308cf79ec95b1aaa05875e', 'description': 'Meet inventory totals through observed resources, tool/station prerequisites, crafting and smelting'}, {'operation_id': 'find_resources', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/resources.py', 'source_sha256': 'e510ed65fc43e561a141296a39606e45157c5ac0e2ededd132812cd299fbac3c', 'description': 'Find resources in a complete local terrain scan'}, {'operation_id': 'mine', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/resources.py', 'source_sha256': 'e510ed65fc43e561a141296a39606e45157c5ac0e2ededd132812cd299fbac3c', 'description': 'Mine the exact observed block'}, {'operation_id': 'mine_and_collect', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/resources.py', 'source_sha256': 'e510ed65fc43e561a141296a39606e45157c5ac0e2ededd132812cd299fbac3c', 'description': 'Mine and prove subsequent item acquisition'}, {'operation_id': 'place_workstation', 'group': 'resources', 'source_relative': 'capability-runtime/mdc_skills/supply.py', 'source_sha256': 'e1333aa2c3b5edad95aa700012a11f09bf05d2f064308cf79ec95b1aaa05875e', 'description': 'Place one owned workstation at an observed clear supported site'}]

DOMAIN_MODULES = tuple("mdc_toolbox.bindings." + name for name in ("managed_navigation","external_navigation","fall_rescue","inventory","interaction","mobility","resources","production","combat","tactical","defensive","dimensions","building","memory","target_actions","typed_portals"))

class CapabilityCatalog:
    def __init__(self, modules=None):
        self._entries, self._plugins, self.load_errors = {}, {}, []
        for source in BASELINE_CAPABILITIES:
            name = source['operation_id']
            self._entries[name] = {
                'capability':name,'capability_version':1,'group':source['group'],'level':'bounded_composite',
                'description':source['description'],'input_schema':obj(),'result_schema':obj(),
                'observation_profile':'local_terrain','native_features':[],'bounds':{},'prerequisites':[],
                'cancel_granularity':'unavailable','resume_supported':False,'planner_available':False,
                'implementation_status':'source_present','adapter_status':'adapter_pending',
                'validation':{'offline':'not_run','live':'not_run'},'known_limits':['Public binding unavailable'],
                'source_fingerprints':[{'path':source['source_relative'],'sha256':source['source_sha256']}]}
        explicit = modules is not None
        for module in (modules if explicit else DOMAIN_MODULES):
            try:
                plugin = importlib.import_module(module) if isinstance(module,str) else module
            except ModuleNotFoundError as exc:
                if not explicit and (exc.name == module or exc.name == 'mdc_toolbox.bindings'):
                    continue
                self.load_errors.append({'module':str(module),'reason':'binding_import_failed'})
                continue
            except Exception:
                self.load_errors.append({'module':str(module),'reason':'binding_import_failed'})
                continue
            definitions = plugin.definitions()
            for definition in definitions:
                # The two new stationary primitives deliberately replace only their
                # unavailable legacy public bindings in the default catalog. Failed
                # new-module import must not silently restore a legacy dispatch path.
                if not explicit and (getattr(plugin, '__name__', ''), definition.get('capability')) in {
                        ('mdc_toolbox.bindings.tactical', 'strike'),
                        ('mdc_toolbox.bindings.dimensions', 'remove_crystal')}:
                    continue
                self._add(plugin,definition)

    def _add(self, plugin, definition):
        required = {'capability','capability_version','group','level','input_schema','result_schema','observation_profile',
                    'native_features','bounds','prerequisites','cancel_granularity','resume_supported','implementation_status',
                    'adapter_status','known_limits','source_fingerprints','validation'}
        if not isinstance(definition,dict) or required - set(definition):
            raise ToolboxError('invalid_catalog','Incomplete domain definition',stage='catalog')
        name = definition['capability']
        if name in self._plugins: raise ToolboxError('invalid_catalog','Duplicate capability binding',stage='catalog')
        if definition['capability_version'] != 1 or definition['resume_supported'] is not False:
            raise ToolboxError('invalid_catalog','Unsupported domain version or resume claim',stage='catalog')
        schema=definition['input_schema']
        if schema.get('type') != 'object' or schema.get('additionalProperties') is not False:
            raise ToolboxError('invalid_catalog','Domain input must be a closed object',stage='catalog')
        entry = deepcopy(definition)
        entry['planner_available'] = bool(definition.get('planner_available',False) and callable(getattr(plugin,'plan',None)))
        self._entries[name],self._plugins[name] = entry,plugin

    def get(self, capability, version=1):
        if version != 1: raise ToolboxError('unsupported_version','Unsupported capability version')
        if capability not in self._entries: raise ToolboxError('capability_unavailable','Unknown capability')
        return deepcopy(self._entries[capability])

    def validate(self, capability, version, arguments):
        definition=self.get(capability,version)
        validate_schema(arguments,definition['input_schema'])
        return definition

    def plugin(self, capability): return self._plugins.get(capability)

    def entry(self, capability, description):
        entry=self.get(capability)
        supported=description.get('supported_capabilities',[])
        features=description.get('native_features',[])
        if isinstance(features,dict): features=[k for k,v in features.items() if v]
        reason=None
        if capability not in self._plugins or entry['adapter_status'] in ('adapter_pending','unavailable'):
            reason='adapter_unavailable'
        elif description.get('available') is not True:
            reason='runtime_unavailable'
        elif description.get('private_singleplayer') is not True:
            reason='private_singleplayer_unverified'
        elif capability not in supported:
            reason='runtime_binding_unavailable'
        elif any(feature not in features for feature in entry.get('native_features',[])):
            reason='native_feature_unavailable'
        entry['runtime_available']=reason is None
        entry['availability_reason']=reason
        return entry

    def page(self, arguments, description):
        selected=[]
        for name in sorted(self._entries):
            entry=self.entry(name,description)
            if arguments.get('group') and arguments['group']!=entry['group']: continue
            if arguments.get('capability_ids') is not None and name not in arguments['capability_ids']: continue
            selected.append(entry)
        offset=int(arguments.get('cursor','0')); limit=arguments.get('limit',64)
        if offset>len(selected): raise ToolboxError('invalid_request','Catalog cursor out of range')
        entries=selected[offset:offset+limit]
        if arguments.get('detail','summary')=='summary':
            entries=[{k:v for k,v in e.items() if k not in ('input_schema','result_schema')} for e in entries]
        return {'api_version':API_VERSION,'versions':{'toolbox':API_VERSION,'capability':1},
                'capabilities':entries,'total':len(selected),'baseline_capability_count':len(BASELINE_CAPABILITIES),
                'runtime_binding_availability':deepcopy(description),
                'budget_defaults':{'max_observations':1024,'reflex_reserve_actions':0,'cleanup_reserve_actions':1},
                'minimum_mutating_action_budget':2,'binding_errors':deepcopy(self.load_errors),
                'next_cursor':str(offset+limit) if offset+limit<len(selected) else None}
