"""Closed single-use item goals and prepared flat portal entry; no discovery or composite activation."""
from copy import deepcopy
from .inventory import _definition
from .interaction import COORDINATE
from mdc_toolbox.contracts import obj, integer, validate_schema, ToolboxError
from mdc_skills import scoped_item_interaction as item, scoped_portal_entry as portal

_SCHEMAS = {
    'ignite_portal_local': obj({'interior_base': COORDINATE, 'axis': {'enum': ['x','z']},
        'width': integer(2,4), 'height': integer(3,4)}, ('interior_base',)),
    'insert_end_eye_local': obj({'interior_corner': COORDINATE, 'target': COORDINATE}, ('interior_corner','target')),
    'enter_portal_local': obj({'portal_cell': COORDINATE,
        'destination': {'enum': ['minecraft:overworld','minecraft:the_nether','minecraft:the_end']},
        'timeout_ms': integer(5000,8000)}, ('portal_cell','destination'))}
_DISPATCH = {'ignite_portal_local': item.ignite_portal_local, 'insert_end_eye_local': item.insert_end_eye_local,
             'enter_portal_local': portal.enter_portal_local}


def definitions():
    result = []
    for name, schema in _SCHEMAS.items():
        entry = name == 'enter_portal_local'
        definition = _definition(name, schema, group='dimensions', level='primitive', profile='local_terrain',
            description={'ignite_portal_local':'Ignite one fully observed obsidian frame with the selected plain flint and steel.',
                'insert_end_eye_local':'Insert exactly one selected eye into an explicit unfilled frame of a verified inward ring.',
                'enter_portal_local':'Enter one exact observed portal over a prepared supported flat corridor and verify the destination.'}[name],
            source='scoped_portal_entry.py' if entry else 'scoped_item_interaction.py',
            actions=['follow_path' if entry else 'interact_block'],
            bounds={'max_mutations':1,'native_timeout_ms':8000 if entry else 3000,'maximum_action_ticks':160 if entry else 60},
            limits=['Request-only and exact dedicated native profile required; no legacy fallback or arbitrary item use.',
                'No hotbar switching, procurement, frame building, repeated insertion, retry or automatic resume.',
                'Consumption, durability and exact block outcome are verified separately; client observations never prove server acknowledgement.',
                'Entry supports only a dry fully supported flat corridor of at most two blocks; natural End drops and credits are unsupported.'])
        definition['native_features'] += ['scoped-native-preflight/1', 'profile:' + (portal.PROFILE if entry else item.PROFILE)]
        definition['cancel_granularity'] = 'exact_native_action'
        result.append(definition)
    return result


def invoke(capability, runtime, arguments, control):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'Unknown typed portal primitive')
    validate_schema(arguments, _SCHEMAS[capability]); control.checkpoint()
    result = _DISPATCH[capability](runtime, **deepcopy(arguments))
    control.emit('capability_result', {'capability':capability,'status':result.status,
        'reason':result.reason,'request_ids':list(result.request_ids)})
    return result
