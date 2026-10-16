"""Synthetic diagnostic fixtures only; no native terrain-equivalence claim."""
from copy import deepcopy
from spatial_stop_fixture import fixture, terminal, witness, movement

PROFILE = 'movement-local-segment-spatial-stop-v1'
POLICY = 'local-segment-terrain-equivalence-v1'
FIELDS = ('loaded', 'id', 'state', 'fluid_empty', 'full_cube', 'collision_empty', 'friction')


def attach_rejection(data, *, phase='equivalence', rejection_code='local_segment_footprint_changed',
                     role='context', current=None, cell_index=None, motion_unknown=False):
    """Mutate the original native result only and return its diagnostic object."""
    native = data if type(data) is dict else data[0]
    profile = witness(native)['profile']
    from spatial_stop_v2_fixture import PROFILE as V2_PROFILE, terminal as v2_terminal
    cells = movement(data)['cells']
    original = deepcopy(cells[cell_index] if cell_index is not None else next(row for row in cells if row['role'] == role))
    baseline = dict(loaded=True, id=original['id'], state=original['state'], role=original['role'],
        fluid_empty=original['fluid'] == 'minecraft:empty', full_cube=original['full_cube'],
        collision_empty=not original['full_cube'], friction=original['friction'])
    observed = {**baseline, 'state': original['state'] + ' [changed]'} if current is None else {**baseline, **deepcopy(current)}
    diagnostic = dict(schema_version=1, profile=profile, policy=POLICY, phase=phase, rejection_code=rejection_code,
        cell={k:original[k] for k in ('x','y','z')}, original=original, current=observed,
        changed_fields=[k for k in FIELDS if observed[k] is not None and observed[k] != baseline[k]])
    native.update(status='cancelled', reason=rejection_code)
    native['result'].update(route_terrain_rejection=diagnostic, input_release_confirmed=True)
    if 'local_segment' not in native['result']:
        native['result']['local_segment'] = (v2_terminal if profile == V2_PROFILE else terminal)(native, landed=False)
    if motion_unknown:
        native['result'].update(unknown_outcome=True, motion_gate_rejected=True,
            motion_gate_reason=rejection_code, effect_outcome='unknown')
    return diagnostic
