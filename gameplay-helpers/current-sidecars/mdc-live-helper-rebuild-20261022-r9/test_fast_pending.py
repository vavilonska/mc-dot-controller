"""Focused sidecar codec/durability/proof tests; no game or live ledger writes.

Optional: --perf-ledger PATH performs one read of that ledger and benchmarks
one original encode versus prepared final persistence in a private tempdir.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'MDC-RECOVERY-RESTORED-F1220-20261022T1433Z/C8-source/survival6-controller'
sys.path[:0] = [str(HERE), str(SOURCE)]
import fast_pending as fp
from survival6_controller.storage import SurvivalLedger, CLEANUP_RESERVE, _StartCapacityProof
from survival6_controller.legacy import encode, strict_json, Refused


def record(action_id, state='CLOSED'):
    return dict(request=dict(id=action_id, profile='recovery_survival_v6'), state=state,
                evidence=[], unknown_reasons=[], latest_native=None,
                terminal_native=None, stop_attempted=False,
                sample={'unicode': '星乃\n"\\', 'array': [None, True, False, -0.0, 1e-9],
                        'nested': {'z': 2, 'a': 1}})


def ledger_at(directory, actions=None):
    ledger = object.__new__(SurvivalLedger)
    ledger.directory = Path(directory)
    ledger.path = ledger.directory / 'ledger.json'
    ledger._save_epoch = 7
    ledger.data = dict(version=1, endpoint='http://127.0.0.1:38121',
                       unknown_lock=False, actions=actions if actions is not None else
                       {'m': record('m'), 'c': record('c')})
    ledger.path.write_bytes(encode(ledger.data))
    ledger.path.chmod(0o600)
    return ledger


class Tests(unittest.TestCase):
    def test_canonical_bytes_exact_for_sorted_insertions_and_empty_history(self):
        for aid in ('a', 'h', 'z', '星'):
            for empty in (False, True):
                with self.subTest(aid=aid, empty=empty), tempfile.TemporaryDirectory() as td:
                    ledger = ledger_at(td, {} if empty else None)
                    before = copy.deepcopy(ledger.data)
                    adapter = fp.PreparedHistory(ledger).install().prepare()
                    rec = record(aid, 'PENDING')
                    expected = encode(dict(before, actions=dict(before['actions'], **{aid: rec})))
                    proof = ledger._save_pending(rec, 4096)
                    self.assertEqual(ledger.path.read_bytes(), expected)
                    self.assertIs(type(proof), _StartCapacityProof)
                    self.assertEqual(proof.raw_size, len(expected))
                    for key, value in before['actions'].items():
                        self.assertEqual(ledger.data['actions'][key], value)
                    proof.consume(ledger, rec)
                    with self.assertRaises(Refused):
                        proof.consume(ledger, rec)

    def test_prepare_reuse_and_postfresh_encodes_only_new_record(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            adapter = fp.PreparedHistory(ledger).prepare()
            prepared = adapter._prepared
            with patch.object(fp, 'encode', side_effect=AssertionError('unexpected history encode')):
                adapter.prepare()
            self.assertIs(adapter._prepared, prepared)
            rec = record('new', 'PENDING')
            seen = []
            def only_new(value):
                self.assertTrue(value is rec or value == 'new')
                seen.append(value)
                return encode(value)
            with patch.object(fp, 'encode', side_effect=only_new):
                adapter.save_pending(rec, 4096)
            self.assertEqual(len(seen), 2)
            with self.assertRaises(Refused):
                adapter.save_pending(record('again', 'PENDING'), 4096)
            self.assertNotIn('again', ledger.data['actions'])

    def test_unprepared_refuses_without_persisting(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            before = ledger.path.read_bytes()
            adapter = fp.PreparedHistory(ledger)
            with self.assertRaises(Refused):
                adapter.save_pending(record('new', 'PENDING'), 4096)
            self.assertEqual(ledger._save_epoch, 8)
            self.assertEqual(ledger.path.read_bytes(), before)
            self.assertNotIn('new', ledger.data['actions'])

    def test_stale_epoch_containers_records_header_set_and_unknown_refuse(self):
        modes = ('epoch', 'data', 'actions', 'record', 'header', 'nested_header',
                 'add', 'remove', 'replace_key', 'pending', 'unknown_lock')
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                ledger = ledger_at(td)
                ledger.data['extra_header'] = {'nested': ['original']}
                adapter = fp.PreparedHistory(ledger).prepare()
                if mode == 'epoch': ledger._save_epoch += 1
                elif mode == 'data': ledger.data = copy.deepcopy(ledger.data)
                elif mode == 'actions': ledger.data['actions'] = dict(ledger.data['actions'])
                elif mode == 'record': ledger.data['actions']['m'] = copy.deepcopy(ledger.data['actions']['m'])
                elif mode == 'header': ledger.data['endpoint'] = 'changed'
                elif mode == 'nested_header': ledger.data['extra_header']['nested'].append('changed')
                elif mode == 'add': ledger.data['actions']['x'] = record('x')
                elif mode == 'remove': del ledger.data['actions']['m']
                elif mode == 'replace_key': ledger.data['actions']['x'] = ledger.data['actions'].pop('m')
                elif mode == 'pending': ledger.data['actions']['m']['state'] = 'PENDING'
                elif mode == 'unknown_lock': ledger.data['unknown_lock'] = True
                disk = ledger.path.read_bytes()
                with self.assertRaises(Refused):
                    adapter.save_pending(record('new', 'PENDING'), 4096)
                self.assertIsNone(adapter._prepared)
                self.assertEqual(ledger.path.read_bytes(), disk)
                self.assertNotIn('new', ledger.data['actions'])

    def test_prepare_unknown_or_pending_is_forbidden(self):
        for state in ('UNKNOWN', 'PENDING'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                ledger = ledger_at(td, {'old': record('old', state)})
                with self.assertRaises(Refused): fp.PreparedHistory(ledger).prepare()

    def test_count_duplicate_codec_and_cleanup_capacity_reject_before_mutation(self):
        for mode in ('count', 'duplicate', 'codec', 'capacity'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                ledger = ledger_at(td)
                rec = record('m' if mode == 'duplicate' else 'new', 'PENDING')
                if mode == 'codec': rec['bad'] = float('nan')
                if mode == 'capacity':
                    prospective = dict(ledger.data, actions=dict(ledger.data['actions'], new=rec))
                    ledger.MAX_BYTES = len(encode(prospective)) + CLEANUP_RESERVE - 1
                adapter = fp.PreparedHistory(ledger).prepare()
                before, disk = copy.deepcopy(ledger.data), ledger.path.read_bytes()
                with self.assertRaises((Refused, ValueError)):
                    adapter.save_pending(rec, 2 if mode == 'count' else 4096)
                self.assertEqual(ledger.data, before)
                self.assertEqual(ledger.path.read_bytes(), disk)
                self.assertIsNone(adapter._prepared)

    def test_atomic_sequence_and_original_proof_fence(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            adapter = fp.PreparedHistory(ledger).prepare()
            events = []
            fsync, replace = os.fsync, os.replace
            def synced(fd):
                events.append('dir_fsync' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file_fsync')
                return fsync(fd)
            def replaced(src, dest):
                events.append('replace')
                return replace(src, dest)
            rec = record('new', 'PENDING')
            with patch.object(fp.os, 'fsync', side_effect=synced), patch.object(fp.os, 'replace', side_effect=replaced):
                proof = adapter.save_pending(rec, 4096)
            self.assertEqual(events, ['file_fsync', 'replace', 'dir_fsync'])
            rec['request']['changed'] = True
            with self.assertRaises(Refused): proof.consume(ledger, rec)
            self.assertTrue(proof.used)

    def test_disk_failures_keep_pending_and_never_produce_proof_or_new_retry(self):
        for operation in ('mkstemp', 'fsync', 'replace'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as td:
                ledger = ledger_at(td)
                adapter = fp.PreparedHistory(ledger).prepare()
                target = fp.tempfile if operation == 'mkstemp' else fp.os
                rec = record('new', 'PENDING')
                with patch.object(target, operation, side_effect=OSError('test disk failure')):
                    with self.assertRaises(OSError): adapter.save_pending(rec, 4096)
                self.assertIs(ledger.data['actions']['new'], rec)
                self.assertEqual(rec['state'], 'PENDING')
                self.assertIsNone(adapter._prepared)
                with self.assertRaises(Refused): adapter.prepare()
                with self.assertRaises(Refused): adapter.save_pending(rec, 4096)
                self.assertEqual(list(Path(td).glob('.ledger-*')), [])

    def test_directory_fsync_failure_leaves_durable_pending_restart_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            adapter = fp.PreparedHistory(ledger).prepare()
            rec = record('new', 'PENDING')
            fsync = os.fsync
            def fail_directory(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError('test directory fsync failure')
                return fsync(fd)
            with patch.object(fp.os, 'fsync', side_effect=fail_directory):
                with self.assertRaises(OSError): adapter.save_pending(rec, 4096)
            self.assertEqual(strict_json(ledger.path.read_bytes())['actions']['new']['state'], 'PENDING')
            with SurvivalLedger(td) as restarted:
                self.assertEqual(restarted.data['actions']['new']['state'], 'UNKNOWN')
                self.assertTrue(restarted.data['unknown_lock'])
                with self.assertRaises(Refused): fp.PreparedHistory(restarted).prepare()

    def test_short_write_keeps_pending_and_original_disk_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            adapter = fp.PreparedHistory(ledger).prepare()
            before = ledger.path.read_bytes()
            fdopen = os.fdopen
            class ShortStream:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
                def write(self, raw): return self.stream.write(raw[:-1])
            rec = record('new', 'PENDING')
            with patch.object(fp.os, 'fdopen', side_effect=lambda fd, mode: ShortStream(fdopen(fd, mode))):
                with self.assertRaises(OSError): adapter.save_pending(rec, 4096)
            self.assertIs(ledger.data['actions']['new'], rec)
            self.assertEqual(rec['state'], 'PENDING')
            self.assertEqual(ledger.path.read_bytes(), before)
            self.assertEqual(list(Path(td).glob('.ledger-*')), [])

    def test_epoch_change_during_persistence_invalidates_original_fence(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ledger_at(td)
            adapter = fp.PreparedHistory(ledger).prepare()
            replace = os.replace
            def changed(src, dest):
                result = replace(src, dest)
                ledger._save_epoch += 1
                return result
            with patch.object(fp.os, 'replace', side_effect=changed):
                with self.assertRaises(Refused): adapter.save_pending(record('new', 'PENDING'), 4096)
            self.assertEqual(ledger.data['actions']['new']['state'], 'PENDING')


def performance(path):
    # Exactly one read of caller-selected retained history; every write is temp.
    raw = Path(path).read_bytes()
    original_sha = hashlib.sha256(raw).hexdigest()
    data = strict_json(raw)
    if data.get('unknown_lock') is not False or any(r.get('state') != 'CLOSED' for r in data['actions'].values()):
        raise Refused('performance input must be entirely CLOSED')
    aid = 'ffffffff-ffff-4fff-bfff-ffffffffffff'
    if aid in data['actions']: raise Refused('performance action ID already present')
    rec = copy.deepcopy(next(reversed(data['actions'].values())))
    rec['request']['id'] = aid
    rec.update(state='PENDING', evidence=[], unknown_reasons=[], latest_native=None,
               terminal_native=None, stop_attempted=False)
    with tempfile.TemporaryDirectory() as td:
        ledger = object.__new__(SurvivalLedger)
        ledger.directory = Path(td); ledger.path = ledger.directory / 'ledger.json'
        ledger._save_epoch = 7; ledger.data = data
        t = time.perf_counter()
        expected = encode(dict(data, actions=dict(data['actions'], **{aid: rec})))
        original_seconds = time.perf_counter() - t
        adapter = fp.PreparedHistory(ledger)
        t = time.perf_counter(); adapter.prepare(); prepare_seconds = time.perf_counter() - t
        t = time.perf_counter(); proof = adapter.save_pending(rec, 4096); pending_seconds = time.perf_counter() - t
        actual = ledger.path.read_bytes()
        assert actual == expected
        proof.consume(ledger, rec)
        return dict(history_count=len(data['actions']) - 1, input_bytes=len(raw),
                    input_sha256=original_sha, prospective_bytes=len(actual),
                    canonical_bytes_equal=True, original_encode_seconds=original_seconds,
                    prepare_before_fresh_seconds=prepare_seconds,
                    prepared_pending_full_durable_seconds=pending_seconds,
                    original_single_use_proof_consumed=True, live_writes=False)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--perf-ledger':
        print(json.dumps(performance(sys.argv[2]), sort_keys=True))
    else:
        unittest.main(verbosity=2)
