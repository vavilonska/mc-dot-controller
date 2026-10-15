#!/usr/bin/env python3
"""Cross-language regression using freshly emitted, entirely synthetic fixtures."""
import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.repo / 'resident-controller'))
    from resident_controller import block_menu_snapshot as b
    from resident_controller.capability_snapshot import validate_scoped_witness
    out = args.output
    checks = 0
    sine = (out / 'engine-sine-table.bin').read_bytes()
    assert len(sine) == 65536 * 4
    for i, (value,) in enumerate(struct.iter_unpack('!f', sine)):
        assert value == b.f32(math.sin(i * math.pi * 2.0 / 65536.0)), i
        checks += 1
    rows = json.loads((out / 'geometry-rows.json').read_text())
    assert len(rows) == 360
    for row in rows:
        try:
            yaw, pitch, hit = b.representable_ray(b.xyz(row['eye']), b.xyz(row['center']),
                                                 b.xyz(row['target']), row['face'])
        except ValueError:
            assert row['admitted'] is False, row
        else:
            assert row['admitted'] is True, row
            assert yaw == row['yaw'] and pitch == row['pitch'], row
            assert math.dist(hit, b.xyz(row['expected'])) < 1e-12, (row, hit)
        checks += 1
    wire = out / 'wire'
    native = json.loads((wire / 'block-menu-standalone.json').read_text())
    scope = json.loads((wire / 'block-menu-request.json').read_text())
    intent = json.loads((wire / 'block-menu-intent.json').read_text())
    coherent = json.loads((wire / 'block-menu-coherent.json').read_text())
    witness = native['result']['scoped_native_preflight']
    b.validate(witness, native, intent)
    checks += 1
    target = intent['target']
    pitch = witness['final_ray']['pitch']
    mutants = {
        'neighbor': lambda w: w['final_ray']['target'].__setitem__('x', target['x'] + 1),
        'wrong_face': lambda w: w['final_ray'].__setitem__('face', 'east'),
        'large_offset': lambda w: w['final_ray']['hit'].__setitem__('y', target['y'] + .51),
        'changed_aim': lambda w: w['final_ray'].__setitem__('pitch', pitch + .01),
        'shortened_reach': lambda w: w['facts']['block_menu'].__setitem__('reach', 1.0),
        'fluid': lambda w: w['facts']['block_menu']['ray_cells'][0].__setitem__('fluid', 'minecraft:water'),
        'wrong_block': lambda w: w['facts']['block_menu']['target'].__setitem__('id', 'minecraft:stone'),
        'outside_certified_prism': lambda w: w['final_ray']['hit'].__setitem__('z', target['z'] + 1.0),
        'edge_face': lambda w: w['final_ray']['hit'].__setitem__('y', float(target['y'])),
        'no_fence': lambda w: w.__setitem__('dispatch_fence_confirmed', False),
    }
    for name, mutate in mutants.items():
        changed = copy.deepcopy(native)
        changed_witness = changed['result']['scoped_native_preflight']
        mutate(changed_witness)
        try:
            b.validate(changed_witness, changed, intent)
        except ValueError:
            checks += 1
        else:
            raise AssertionError(name)
    wire_checks = []
    for key, action in [('standalone', native), ('coherent_action', coherent['action']),
                        ('coherent_status', coherent['status']['client_action']),
                        ('coherent_state', coherent['state']['client_action'])]:
        value = validate_scoped_witness(action, scope, native['action_id'], intent)
        assert value['profile'] == 'block-menu-v1'
        assert action['result'] == native['result']
        assert (action['status'], action['reason'], action['action_id']) == (
            native['status'], native['reason'], native['action_id'])
        wire_checks.append(key + ': full witness and exact terminal equality')
    # Explicit negative control: an ideal center is not the actual quantized hit.
    ideal = copy.deepcopy(native)
    ideal_witness = ideal['result']['scoped_native_preflight']
    ideal_witness['final_ray']['hit'] = copy.deepcopy(ideal_witness['facts']['block_menu']['expected_hit'])
    try:
        validate_scoped_witness(ideal, scope, ideal['action_id'], intent)
    except ValueError as error:
        assert str(error) == 'block_menu_final_actual_ray', str(error)
        wire_checks.append('synthetic ideal-center counterfeit rejected')
    else:
        raise AssertionError('ideal-center counterfeit accepted')
    fixture_path = args.repo / 'capability-runtime/tests/mining_collect/collect/menu_fixture.py'
    spec = importlib.util.spec_from_file_location('menu_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    assert validate_scoped_witness(*fixture.fixture())['profile'] == 'state-menu-v1'
    wire_checks.append('existing exact state-menu source fixture unchanged')
    failed = copy.deepcopy(native)
    failed['status'], failed['reason'] = 'failed', 'client_action_error'
    result = failed['result']
    result['dispatched'], result['local_click_hooks_started'] = False, True
    result.pop('local_use_started')
    result['scoped_native_preflight']['dispatch_fence_confirmed'] = False
    result['scoped_native_preflight'].pop('final_ray')
    try:
        validate_scoped_witness(failed, scope, failed['action_id'], intent)
    except ValueError as error:
        assert str(error) == 'block_menu_late_local_effect_unknown', str(error)
        wire_checks.append('post-click unknown remains inadmissible')
    else:
        raise AssertionError('post-click unknown accepted')
    result = {'status': 'passed', 'assertions': checks, 'lut_entries': 65536,
              'geometry_rows': len(rows), 'wire_mutants': list(mutants),
              'wire_checks': wire_checks, 'fixture_origin': 'source-defined synthetic origin',
              'limits': ['No saved-world or observed-action inputs.',
                         'No game, renderer, world, HTTP server, or native use startup.',
                         'Cross-runtime atan2/hypot boundary differences may still fail closed.']}
    (out / 'block-menu-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
