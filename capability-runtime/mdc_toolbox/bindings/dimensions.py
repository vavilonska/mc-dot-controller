"""Independent portal/End mechanics with typed data and explicit evidence limits."""
from copy import deepcopy
from pathlib import Path
import hashlib
from mdc_skills import dimensions as skills, expedition
from mdc_skills.core import Outcome
from mdc_toolbox.contracts import ToolboxError, validate_schema, obj, integer
from .tactical import UUID, COORD, HEALTH, number, default, definition

_CRYSTAL = obj({'uuid': UUID, 'firing_station': COORD,
    'cage_bars': {'type': 'array', 'items': COORD, 'maxItems': 8, 'uniqueItems': True},
    'cage_station': COORD}, ('uuid',))
_SCHEMAS = {
    'ignite_nether_portal': obj({'interior_base': COORD, 'axis': default({'enum': ['x', 'z']}, 'x'),
        'width': default(integer(2, 4), 2), 'height': default(integer(3, 4), 3),
        'hotbar_slot': default(integer(0, 8), 0)}, ('interior_base',)),
    'activate_end_portal': obj({'interior_corner': COORD, 'max_eyes': default(integer(1, 12), 12),
        'hotbar_slot': default(integer(0, 8), 0)}, ('interior_corner',)),
    'enter_portal': obj({'portal_cell': COORD, 'destination': {'enum': [skills.OVERWORLD, skills.NETHER, skills.END]},
        'timeout_ms': default(integer(5000, 30000), 10000)}, ('portal_cell', 'destination')),
    'remove_crystal': obj({'target_uuid': UUID, 'hotbar_slot': default(integer(0, 8), 0),
        'min_health': default(HEALTH, 12)}, ('target_uuid',)),
    'open_crystal_cage': obj({'crystal_uuid': UUID,
        'bars': {'type': 'array', 'items': COORD, 'minItems': 1, 'maxItems': 16, 'uniqueItems': True},
        'max_blocks': default(integer(1, 16), 8), 'hotbar_slot': integer(0, 8)}, ('crystal_uuid', 'bars')),
    'wait_dragon_phase': obj({'dragon_uuid': UUID, 'max_samples': default(integer(1, 128), 80),
        'min_health': default(HEALTH, 12)}, ('dragon_uuid',)),
    'discover_end_goals': obj({'max_targets': default(integer(1, 10), 10), 'min_health': default(HEALTH, 12)}),
    'clear_observed_crystals': obj({'max_crystals': default(integer(1, 10), 3),
        'min_health': default(HEALTH, 12), 'bow_slot': default(integer(0, 8), 0)}),
    'deflect_shulker_bullet': obj({'bullet_uuid': UUID, 'min_health': default(HEALTH, 12)}, ('bullet_uuid',)),
    'end_battle': obj({'dragon_uuid': UUID, 'crystals': {'type': 'array', 'items': _CRYSTAL, 'maxItems': 10},
        'max_strikes': default(integer(1, 256), 64), 'max_phase_samples': default(integer(1, 128), 80),
        'min_health': default(HEALTH, 12), 'bow_slot': default(integer(0, 8), 0),
        'weapon_slot': default(integer(0, 8), 1), 'cage_tool_slot': default(integer(0, 8), 2),
        'dragon_station': COORD, 'exit_portal': COORD}, ('dragon_uuid',)),
    'end_expedition': obj({'boxes': default(integer(1, 8), 1), 'max_actions': default(integer(1, 8192), 4096),
        'max_seconds': default(integer(1, 86400), 7200), 'max_walk_distance': default(integer(1, 65536), 8192),
        'max_search_steps': default(integer(1, 4096), 512), 'max_crystals': default(integer(1, 32), 16),
        'max_dragon_strikes': default(integer(1, 512), 256), 'max_shulker_strikes': default(integer(1, 512), 64),
        'block_id': default({'enum': sorted(expedition.FULL_BLOCKS)}, 'minecraft:cobblestone'),
        'min_health': {'type': 'number', 'minimum': 12, 'exclusiveMaximum': 15, 'default': 12}}),
}
_SPECS = {
    'ignite_nether_portal': ('primitive', 'local_terrain', ('interact_block', 'select_hotbar', 'click_slot'),
        'Ignite a complete exact observed obsidian frame.', ['Only 2–4 wide, 3–4 high frames; does not build or repair frames.']),
    'activate_end_portal': ('bounded_composite', 'local_terrain', ('interact_block', 'select_hotbar', 'click_slot'),
        'Insert bounded eyes into observed inward-facing frames and verify all nine portal cells.',
        ['Must stand outside a complete 12-frame Overworld ring; exact eyes and actual reach required.']),
    'enter_portal': ('primitive', 'local_terrain', ('follow_path',),
        'Enter one observed portal and prove the exact expected dimension and safe landing.',
        ['Prepared flat dry supported entry within two blocks only.',
         'Same-server/world-transition identity stays guarded; delayed transition is never a replay permission.',
         'No arbitrary cross-save transition, unsupported drop, credits screen or unobserved landing acceptance.']),
    'remove_crystal': ('primitive', 'entities', ('shoot_entity', 'select_hotbar', 'click_slot'),
        'One guarded shot with stable removal from a loaded observed area.',
        ['12–32 block station, exact loaded target chunk and native ballistic corridor required.',
         'Local disappearance is not causal destruction attribution or all-world crystal absence.']),
    'open_crystal_cage': ('bounded_composite', 'local_terrain', ('break_block',),
        'Mine exact caller-selected observed cage bars without hitting the crystal.',
        ['Selected bars within reach only; removing them does not prove a clear firing lane.']),
    'wait_dragon_phase': ('query', 'entities', (),
        'Read-only bounded observation of a visible dragon and safe perched phase.',
        ['Perched phases 6/7 or an observed dead dragon only; missing target is never victory.']),
    'discover_end_goals': ('query', 'local_terrain', (),
        'Discover loaded local End targets with explicit per-target blockers.',
        ['48-block local discovery; does not grant action authority or global absence proof.']),
    'clear_observed_crystals': ('bounded_composite', 'local_terrain', ('shoot_entity', 'select_hotbar', 'click_slot'),
        'Remove a bounded subset of currently observed safely actionable crystals.',
        ['Only independently actionable local targets; no tower/city/stronghold planner.']),
    'deflect_shulker_bullet': ('primitive', 'entities', ('attack_entity',),
        'Intercept one exact observed shulker bullet with later removal proof.',
        ['Bullet disappearance is local interception evidence, not a shulker kill or shell drop.']),
    'end_battle': ('bounded_composite', 'local_terrain', ('follow_path', 'break_block', 'shoot_entity', 'attack_entity', 'select_hotbar', 'click_slot'),
        'Experimental composition of typed crystal/cage/station and perched-dragon goals.',
        ['Experimental and unvalidated; broad End completion is not required for independent portal/local tools.',
         'At most ten typed CrystalGoal values; no executable object or arbitrary callback is accepted.',
         'Exact death and observed exit evidence remain independent; no guaranteed victory.']),
    'end_expedition': ('bounded_composite', 'local_terrain', ('follow_path', 'break_block', 'place_block',
        'shoot_entity', 'attack_entity', 'gateway_pearl', 'click_slot', 'use_item', 'select_hotbar', 'interact_block', 'close_menu'),
        'Experimental existing bounded End expedition; not the toolbox architecture root.',
        ['Experimental/unvalidated; existing actual-dragon, gateway, shell and craft evidence chain is unchanged.',
         'The toolbox job identity selects a new private checkpoint; existing checkpoint execution and resume are refused.',
         'No caller job path, resume flag, checkpoint content, or new strategic framework.',
         'Legacy walk reservation is planned route allocation, not strict actual physical distance.']),
}


def definitions():
    output = []
    for name, spec in _SPECS.items():
        row = definition(name, _SCHEMAS[name], group='dimensions_end', level=spec[0], profile=spec[1],
            sources=(skills, expedition), actions=spec[2], description=spec[3], limits=spec[4],
            bounds={'argument_bounds': 'input_schema', 'shared_budget': 'original_job_ledger'},
            experimental=name in ('end_battle', 'end_expedition'))
        path = Path(__file__)
        row['source_fingerprints'].append({'path': 'capability-runtime/mdc_toolbox/bindings/dimensions.py',
                                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        output.append(row)
    return output


_DISPATCH = {name: getattr(expedition if name in ('deflect_shulker_bullet', 'end_expedition') else skills, name)
             for name in _SCHEMAS}


def invoke(capability, runtime, arguments, control):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'Unknown dimension capability')
    validate_schema(arguments, _SCHEMAS[capability])
    values = deepcopy(arguments)
    if capability == 'open_crystal_cage' and len(values['bars']) > values.get('max_blocks', 8):
        raise ToolboxError('invalid_request', 'bars exceed max_blocks')
    if capability == 'end_battle':
        rows = values.get('crystals', [])
        if len({row['uuid'] for row in rows}) != len(rows):
            raise ToolboxError('invalid_request', 'Duplicate crystal UUID')
        values['crystals'] = [skills.CrystalGoal(**{**row, 'cage_bars': tuple(row.get('cage_bars', []))}) for row in rows]
    control.checkpoint()
    if capability == 'end_expedition':
        job_id = getattr(control, 'job_id', None)
        if not isinstance(job_id, str) or not expedition.ID.fullmatch(job_id):
            raise ToolboxError('invalid_request', 'Trusted toolbox job identity required')
        path = expedition._path(runtime, job_id)
        if path.exists() or path.is_symlink():
            return Outcome('blocked', 'existing_expedition_checkpoint_no_resume', (),
                {'server_confirmed': False, 'goal_completed': False, 'continuation': 'none'})
        values.update(job_id=job_id, resume=False)
    result = _DISPATCH[capability](runtime, **values)
    control.emit('dimension_goal_observed' if result.ok else 'dimension_goal_stopped', {
        'capability': capability, 'status': result.status, 'reason': result.reason,
        'request_ids': list(result.request_ids)})
    return result
