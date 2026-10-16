"""Synthetic closed consumer checks. Never reclassifies a retained live unknown job."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.spatial_threat_snapshot import validate_defense_stop, MAX_STOP_PROOF_BYTES
from spatial_threat_fixture import fixture, terminal, threat_stop, zombie_row, TARGET
from mining_collect.collect.collect_fixture import redigest


def add_passive_rows(native, count=30):
    """A legal populated scene, with only the selected zombie threatening the player."""
    w = native['result']['scoped_native_preflight']
    frame = w['facts']['local_segment']['entity_guard']
    for n in range(count):
        row = zombie_row(w, frame, uuid=f'00000000-0000-4000-8000-{n+100:012d}', entity_id=n+100)
        row.update(type='minecraft:cow', **{'class':'net.minecraft.world.entity.animal.Cow'})
        del row['native_living']
        frame['rows'].append(row)
    frame['rows'].sort(key=lambda r:(r['id'],r['uuid'],r['class']))
    frame.update(enumerated_count=len(frame['rows'])+1, live_other_count=len(frame['rows']), removed_count=0)
    native['result']['local_segment'] = terminal(native, landed=False, effect_attempted=False)
    native['result']['route_threat_stop'] = threat_stop(native)


def failure(reason='local_segment_check_failed', *, checks=1):
    data = fixture(stop_only=True)
    native, _, _, intent = data
    intent['route_stop_only'] = True
    redigest(native, intent)
    del native['result']['route_threat_stop']
    native['reason'] = reason
    if checks == 0:
        t = native['result']['local_segment']
        frame = native['result']['scoped_native_preflight']['facts']['local_segment']['entity_guard']
        t.update(local_checks=0, entity_guard_checks=0, last_entity_check_nano=frame['source_nano'])
    return data


class StopOnlyFailureContractTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            validate_scoped_witness(*data)

    def test_known_no_effect_proof_failure_does_not_authorize_defense(self):
        for reason in ('local_segment_check_failed', 'route_spatial_stop_evidence_too_large', 'route_spatial_evidence_too_large'):
            for checks in (0, 1):
                data = failure(reason, checks=checks)
                validate_scoped_witness(*data)
                self.assertNotIn('route_threat_stop', data[0]['result'])
                with self.assertRaises(ValueError):validate_defense_stop(data[0], TARGET)

    def test_known_failure_requires_original_identity_and_command(self):
        good = failure()
        for key, value in (('action_id', 'replacement'), ('action_session', 'replacement'),
                           ('status', 'running'), ('status', 'succeeded'), ('status', 'failed'),
                           ('ticks', 1), ('ticks', True), ('reason', 'capability_threat_observed'),
                           ('reason', 'capability_damage_observed'), ('reason', 'cancel_requested')):
            bad = deepcopy(good);bad[0][key] = value
            with self.subTest(key=key, value=value):self.reject(bad)
        bad = deepcopy(good);bad[3]['timeout_ms'] += 1;self.reject(bad)
        bad = deepcopy(good);bad[0]['result']['scoped_native_preflight']['owner_generation'] += 1;self.reject(bad)
        bad = deepcopy(good);bad[0]['result']['route_threat_stop'] = {};self.reject(bad)

    def test_partial_effect_or_uncertainty_cannot_be_downgraded(self):
        good = failure()
        for key, value in (('effect_attempted', True), ('phase', 'landed'), ('landed', True),
                           ('sampled_horizontal_distance', .001), ('jump_pulses', 1),
                           ('input_neutral', False), ('local_checks', 2), ('entity_guard_checks', 0),
                           ('last_entity_check_action_tick', 1), ('last_entity_check_tick', 101),
                           ('last_entity_check_nano', '1'), ('maximum_checked_population', 1)):
            bad = deepcopy(good);bad[0]['result']['local_segment'][key] = value
            with self.subTest(key=key):self.reject(bad)
        for where in ('root', 'result'):
            for key in ('unknown_outcome', 'motion_gate_rejected', 'requires_handoff',
                        'input_release_unconfirmed', 'post_uncertain', 'uncertain'):
                for value in (True, 0, None):
                    bad = deepcopy(good);(bad[0] if where == 'root' else bad[0]['result'])[key] = value
                    with self.subTest(where=where,key=key,value=value):self.reject(bad)
        for source in (good, fixture(stop_only=True)):
            for where in ('root', 'result'):
                for value in ('unknown', 'known', False, None):
                    bad = deepcopy(source);(bad[0] if where == 'root' else bad[0]['result'])['effect_outcome'] = value
                    self.reject(bad)
        for value in (False, 1, None):
            bad = deepcopy(good);bad[0]['result']['input_release_confirmed'] = value;self.reject(bad)
        bad = deepcopy(good);del bad[0]['result']['local_segment'];self.reject(bad)
        bad = deepcopy(good);w = bad[0]['result']['scoped_native_preflight']
        bad[0]['result']['local_segment']['last_entity_check_nano'] = w['facts']['local_segment']['deadline_nano']
        self.reject(bad)
        bad = failure(checks=0);bad[0]['result']['local_segment']['last_entity_check_nano'] = '1000001';self.reject(bad)

    def test_python_complete_proof_exact_boundary(self):
        # Removed rows are still fully enumerated; long class labels are bounded
        # by evidence capacity rather than silently dropped from the proof.
        for delta in (-1, 0, 1):
            data = fixture(stop_only=True)
            w = data[0]['result']['scoped_native_preflight']
            frame = w['facts']['local_segment']['entity_guard']
            row = dict(id=100, uuid='00000000-0000-4000-8000-000000000100',
                       type='minecraft:cow', **{'class':'x'}, removed=True)
            frame['rows'].append(row)
            frame.update(enumerated_count=3, live_other_count=1, removed_count=1)
            data[0]['result']['local_segment'] = terminal(data[0], landed=False, effect_attempted=False)
            stop = threat_stop(data[0])
            size = len(json.dumps(stop, ensure_ascii=False, separators=(',', ':')).encode())
            row['class'] += 'x' * (MAX_STOP_PROOF_BYTES + delta - size)
            data[0]['result']['route_threat_stop'] = threat_stop(data[0])
            actual = len(json.dumps(data[0]['result']['route_threat_stop'],
                                   ensure_ascii=False, separators=(',', ':')).encode())
            self.assertEqual(actual, MAX_STOP_PROOF_BYTES + delta)
            if delta <= 0:validate_scoped_witness(*data)
            else:
                with self.assertRaisesRegex(ValueError, 'route_threat_stop_size'):
                    validate_scoped_witness(*data)

    def test_large_legal_stop_proof_and_whole_envelope_bound(self):
        data = fixture(stop_only=True);add_passive_rows(data[0])
        stop = data[0]['result']['route_threat_stop']
        size = len(json.dumps(stop, ensure_ascii=False, separators=(',', ':')).encode())
        self.assertGreater(size, 16 * 1024);self.assertLess(size, MAX_STOP_PROOF_BYTES)
        validate_scoped_witness(*data);validate_defense_stop(data[0], TARGET)
        bad = deepcopy(data)
        bad[0]['result']['route_threat_stop']['dimension'] = 'x' * MAX_STOP_PROOF_BYTES
        with self.assertRaisesRegex(ValueError, 'route_threat_stop_size'):
            validate_scoped_witness(*bad)
        too_large = fixture(stop_only=True);add_passive_rows(too_large[0], 70)
        self.reject(too_large)


@unittest.skipUnless(os.environ.get('MDC_STOP_PROOF_NATIVE_WIRE'), 'explicit current native wire directory required')
class StopProofNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['MDC_STOP_PROOF_NATIVE_WIRE'])
        cls.values = {kind: {name: json.loads((cls.root/kind/f'generated-{name}.json').read_text())
            for name in ('standalone', 'coherent', 'intent', 'request')}
            for kind in ('spatial-large-stop', 'spatial-failure-generic', 'spatial-failure-size', 'spatial-failure-frame-size')}

    def test_actual_java_large_proof_and_no_proof_failure_consumers(self):
        from resident_controller.capability_snapshot import validate_snapshot
        from resident_controller.movement_wire import retain, validate_retained
        for kind, source in self.values.items():
            native, scope, intent = (deepcopy(source[n]) for n in ('standalone', 'request', 'intent'))
            with self.subTest(kind=kind):
                validate_scoped_witness(native, scope, native['action_id'], intent)
                self.assertEqual(native['status'], 'cancelled')
                self.assertIs(native['result']['local_segment']['effect_attempted'], False)
                if kind == 'spatial-large-stop':
                    stop = validate_defense_stop(native, intent['route_threat_guard']['target_uuid'])
                    self.assertGreater(len(json.dumps(stop, separators=(',', ':')).encode()), 16*1024)
                else:
                    self.assertNotIn('route_threat_stop', native['result'])
                    self.assertEqual(native['reason'], 'local_segment_check_failed'
                        if kind.endswith('generic') else 'route_spatial_evidence_too_large'
                        if kind.endswith('frame-size') else 'route_spatial_stop_evidence_too_large')
                    with self.assertRaises(ValueError):validate_defense_stop(native, intent['route_threat_guard']['target_uuid'])
                raw = (self.root/kind/'generated-coherent.json').read_bytes()
                radius = source['coherent']['state']['nearby']['radius']
                semantic = validate_snapshot(source['coherent'], radius)
                self.assertEqual(validate_retained(retain(raw), semantic, radius), semantic)
                validate_scoped_witness(semantic['action'], scope, native['action_id'], intent)
                self.assertLessEqual(len(raw), 256*1024)

    def test_actual_native_failure_through_resident_terminal_acceptance(self):
        from resident_controller.controller import Resident, Running, TaskEnded
        for kind in ('spatial-failure-generic', 'spatial-failure-size', 'spatial-failure-frame-size'):
            source = self.values[kind]
            native, scope, intent = (deepcopy(source[n]) for n in ('standalone', 'request', 'intent'))
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                resident = Resident(object(), directory)
                resident.bridge_identity = {'action_session': native['action_session']}
                task = Running({'scoped_native_preflight': scope, 'action': 'follow_path'}, None,
                    action_id=native['action_id'], scoped_original_intent=deepcopy(intent))
                terminals = []
                resident.end_active = lambda status, **kw: terminals.append((status, kw))
                with self.assertRaises(TaskEnded):resident.accept_action_status(task, native)
                self.assertEqual(terminals[0][0], 'cancelled')
                self.assertEqual(terminals[0][1]['reason'], native['reason'])
                self.assertEqual(terminals[0][1]['action'], native)
                self.assertIsNone(task.action_id)
                self.assertEqual(task.last_action_result, native)

    def test_actual_native_failure_corruption_keeps_original_id_uncertain(self):
        from resident_controller.controller import Resident, Running
        from resident_controller.transport import BridgeError
        for kind in ('spatial-failure-generic', 'spatial-failure-size', 'spatial-failure-frame-size'):
            source = self.values[kind]
            for mutation in ('identity', 'digest', 'release', 'effect', 'effect_outcome', 'unknown'):
                native, scope, intent = (deepcopy(source[n]) for n in ('standalone', 'request', 'intent'))
                original_id = native['action_id']
                if mutation == 'identity':native['action_id'] = 'unrelated-action'
                elif mutation == 'digest':native['result']['scoped_native_preflight']['command_sha256'] = '0'*64
                elif mutation == 'release':native['result']['input_release_confirmed'] = False
                elif mutation == 'effect':native['result']['local_segment']['effect_attempted'] = True
                elif mutation == 'effect_outcome':native['result']['effect_outcome'] = 'unknown'
                else:native['result']['unknown_outcome'] = True
                with self.subTest(kind=kind, mutation=mutation), tempfile.TemporaryDirectory() as directory:
                    resident = Resident(object(), directory)
                    resident.bridge_identity = {'action_session': native['action_session']}
                    task = Running({'scoped_native_preflight': scope, 'action': 'follow_path'}, None,
                        action_id=original_id, scoped_original_intent=deepcopy(intent))
                    with self.assertRaises(BridgeError) as rejected:resident.accept_action_status(task, native)
                    self.assertTrue(rejected.exception.uncertain)
                    self.assertEqual(task.action_id, original_id)
                    self.assertIsNone(task.last_action_result)


if __name__ == '__main__':unittest.main()
