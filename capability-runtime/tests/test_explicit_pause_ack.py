"""Offline public pause acknowledgment through real owner/mailbox components.

Only native Endpoint responses are synthetic. No game, GUI, native JVM, or
installed control directory is used. The Node case uses production executeToolbox
and forwards its unchanged validated request into this same Python chain.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_capability_ownership as owners
import test_scoped_combat_chain as combat
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller import pause_acknowledgment as proof


SOURCE = Path(__file__).resolve().parents[2]


class PauseEndpoint(combat.Endpoint):
    def __init__(self):
        super().__init__()
        self.paused = False
        self.screen_open = False
        self.forced_tick = None
        self.reads = []

    def snapshot(self):
        value = super().snapshot()
        value.update(paused=self.paused, screen_open=self.screen_open)
        if self.forced_tick is not None:
            value['world']['game_time'] = self.forced_tick
            value['capability_guard']['source_tick'] = self.forced_tick
        self.reads.append({'tick': value['world']['game_time'],
                           'paused': value['paused'], 'screen_open': value['screen_open']})
        return value

    def request(self, method, path, body=None):
        if path == '/control/screen':
            return {'ok': True, 'open': self.screen_open}
        return super().request(method, path, body)


class RequestOnlyWatchdog(owners.Watchdog):
    def __init__(self, *args, **kwargs):
        kwargs['execution_policy'] = 'request_only'
        super().__init__(*args, **kwargs)


class ExplicitPauseAcknowledgmentChainTests(unittest.TestCase):
    until = owners.ActualGatewayOwnershipTests.until

    def setUp(self):
        # These are fixture selection/configuration only. No owner, transport,
        # validation, acknowledgment or dispatch method is replaced.
        with patch.object(owners, 'CombatEndpoint', PauseEndpoint), patch.object(owners, 'Watchdog', RequestOnlyWatchdog):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime = Runtime(self.client, self.root / 'runtime', wait_timeout=2,
                               required_execution_policy='request_only')
        self.backend = OwnerRuntimeBackend(self.runtime)
        self.service = ToolboxService(self.backend, self.root / 'toolbox')
        self.call_threads = []
        for name in ('mdc_toolbox.service', 'mdc_toolbox.runtime_adapter', 'mdc_skills.core',
                     'intent_client', 'watchdog', 'base_watchdog', 'capability_ownership',
                     'resident_controller.ipc', 'resident_controller.controller',
                     'pause_acknowledgment', 'resident_controller.pause_acknowledgment'):
            self.assertTrue(Path(sys.modules[name].__file__).resolve().is_relative_to(SOURCE), name)
        self.assertEqual(self.client.session()['execution_policy'], 'request_only')

    def tearDown(self):
        for thread in self.call_threads:
            thread.join(timeout=8)
        self.assertFalse(any(t.is_alive() for t in self.call_threads))
        self.service.close()
        self.runtime.close()
        owners.ActualGatewayOwnershipTests.tearDown(self)

    def pause(self):
        self.bridge.paused = self.bridge.screen_open = True
        self.until(lambda: self.client.session()['state'] == 'paused')
        info = self.backend.describe()['pause_acknowledgment']
        self.assertTrue(info['eligible'], (info, self.dog.reason))
        self.assertFalse(info['automatic_resume'])
        self.assertTrue(info['new_requests_only'])
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.bridge.posts, [])
        return self.ack_args()

    def unpause(self):
        self.bridge.paused = self.bridge.screen_open = False

    def ack_args(self, request_id='explicit_ack_once'):
        description = self.backend.describe()
        return {'api_version': 'mdc.toolbox/1', 'operation': 'acknowledge_pause',
                'request_id': request_id, 'session_ref': description['session_ref'],
                'pause_ref': description['pause_acknowledgment']['pause_ref'],
                'acknowledgment': proof.ACK}

    def begin_ack(self, args):
        output = {}
        def invoke():
            try:
                output['result'] = self.service.call('mdc_job', args)
            except BaseException as exc:
                output['exception'] = exc
        thread = threading.Thread(target=invoke, daemon=True)
        self.call_threads.append(thread)
        thread.start()
        self.until(lambda: getattr(self.dog, '_pause_ack_pending', None) is not None or output)
        self.assertFalse(output, output)
        return thread, output

    def finish_ack(self, call):
        thread, output = call
        thread.join(timeout=8)
        self.assertFalse(thread.is_alive(), output)
        self.assertNotIn('exception', output)
        return output['result']

    def assert_success(self, result, args, old_epoch):
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['request_id'], args['request_id'])
        self.assertEqual(result['continuation'], 'none')
        p = result['result']['pause_acknowledgment']
        self.assertIs(p['rearmed'], True)
        self.assertIs(p['no_task_resume'], True)
        self.assertIs(p['no_native_mutation'], True)
        self.assertEqual(p['command']['pause_ref'], args['pause_ref'])
        self.assertEqual(len(p['samples']), 2)
        self.assertLess(p['origin']['pause_tick'], p['samples'][0]['tick'])
        self.assertLess(p['samples'][0]['tick'], p['samples'][1]['tick'])
        self.assertNotEqual(p['samples'][0]['request_id'], p['samples'][1]['request_id'])
        # Both samples must exist as actual Resident receipts, not fabricated
        # gateway observations, and must preserve the original Resident session.
        for sample in p['samples']:
            receipt = json.loads((self.root / 'resident' / 'results' / (sample['request_id'] + '.json')).read_text())
            self.assertEqual(receipt['session_id'], p['origin']['resident_session'])
            self.assertEqual(receipt['status'], 'succeeded')
            self.assertEqual(receipt['result']['state']['world']['game_time'], sample['tick'])
            self.assertIs(receipt['result']['state']['paused'], False)
            self.assertIs(receipt['result']['state']['screen_open'], False)
        self.assertEqual(len(result['request_ids']), 1)
        receipt = self.client.result(result['request_ids'][0])
        self.assertIsNone(receipt['queue_request_id'])
        proof.validate(receipt, p['command'], result['request_ids'][0], self.client.session()['session_id'])
        self.assertEqual(self.client.session()['defense_epoch'], old_epoch + 1)
        self.assertTrue(self.dog.armed)
        self.assertIsNone(self.dog.owner)
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertFalse(self.backend.describe()['pause_acknowledgment']['eligible'])
        self.assertFalse(self.runtime.has_unresolved_execution)
        self.assertEqual(self.bridge.posts, [])

    def independent_read(self, request_id='new_independent_read'):
        return self.service.call('mdc_observe', {'api_version': 'mdc.toolbox/1',
            'request_id': request_id, 'session_ref': self.backend.describe()['session_ref'], 'profile': 'player'})

    def test_unpause_alone_never_rearms_or_resumes(self):
        self.pause()
        epoch = self.dog.defense_epoch
        before = len(self.bridge.reads)
        self.unpause()
        self.until(lambda: len(self.bridge.reads) >= before + 4)
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.client.session()['state'], 'paused')
        self.assertEqual(self.dog.defense_epoch, epoch)
        self.assertEqual(self.independent_read()['error']['code'], 'capability_unavailable')
        self.assertEqual(self.bridge.posts, [])
        self.assertEqual(list((self.root / 'watchdog' / 'results').glob('pause_*.json')), [])

    def test_explicit_ack_needs_two_new_increasing_ticks_then_distinct_read(self):
        args = self.pause()
        epoch = self.dog.defense_epoch
        first_tick = self.dog._pause_ack_origin['pause_tick'] + 1
        self.bridge.forced_tick = first_tick
        self.unpause()
        call = self.begin_ack(args)
        self.until(lambda: len(self.dog._pause_ack_pending['samples']) == 1)
        before = len(self.bridge.reads)
        self.until(lambda: len(self.bridge.reads) >= before + 3)
        self.assertFalse(self.dog.armed)
        self.assertEqual(len(self.dog._pause_ack_pending['samples']), 1)
        self.bridge.forced_tick = first_tick + 1
        result = self.finish_ack(call)
        self.assert_success(result, args, epoch)
        self.bridge.forced_tick = None
        read = self.independent_read()
        self.assertEqual(read.get('job_state'), 'succeeded', read)
        self.assertEqual(read['job_request_id'], 'new_independent_read')
        self.assertNotEqual(read['job_id'], result['job_id'])
        self.assertTrue(set(read['request_ids']).isdisjoint(result['request_ids']))
        self.assertEqual(self.bridge.posts, [])

    def test_ack_while_still_paused_waits_until_explicitly_unpaused(self):
        args = self.pause()
        epoch = self.dog.defense_epoch
        call = self.begin_ack(args)
        before = len(self.bridge.reads)
        self.until(lambda: len(self.bridge.reads) >= before + 3)
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.dog._pause_ack_pending['samples'], [])
        self.assertEqual(self.bridge.posts, [])
        self.unpause()
        self.assert_success(self.finish_ack(call), args, epoch)

    def test_duplicate_original_request_never_reissues_control(self):
        args = self.pause()
        epoch = self.dog.defense_epoch
        call = self.begin_ack(args)
        pending = self.service.call('mdc_job', deepcopy(args))
        self.assertEqual(pending['state'], 'running', pending)
        self.unpause()
        result = self.finish_ack(call)
        self.assert_success(result, args, epoch)
        again = self.service.call('mdc_job', deepcopy(args))
        self.assertEqual(again['job_id'], result['job_id'])
        self.assertEqual(again['request_ids'], result['request_ids'])
        self.assertEqual(again['state'], 'succeeded')
        self.assertEqual(pending['request_ids'], result['request_ids'])
        self.assertEqual(len(list((self.root / 'watchdog' / 'results').glob('pause_*.json'))), 1)
        self.assertEqual(self.dog.defense_epoch, epoch + 1)
        conflict = self.service.call('mdc_job', {**args, 'pause_ref': '0' * 64})
        self.assertEqual(conflict['error']['code'], 'request_conflict')
        self.assertEqual(self.bridge.posts, [])

    def test_stale_pause_and_session_refs_refuse_without_control(self):
        args = self.pause()
        self.unpause()
        for update in ({'pause_ref': '0' * 64}, {'session_ref': 'stale-session'}):
            with self.subTest(update=update):
                result = self.service.call('mdc_job', {**args, **update})
                self.assertEqual(result['error']['code'], 'policy_violation', result)
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.bridge.posts, [])
        self.assertEqual(list((self.root / 'watchdog' / 'results').glob('pause_*.json')), [])

    def test_unknown_native_owner_cannot_be_cleared_by_pause_ack(self):
        self.bridge.combat_mode = 'lost'
        description = self.backend.describe()
        submitted = self.service.call('mdc_job', {'api_version': 'mdc.toolbox/1',
            'operation': 'submit', 'request_id': 'original_unknown_job',
            'session_ref': description['session_ref'], 'expected_context_ref': description['context_ref'],
            'capability': 'engage', 'capability_version': 1,
            'arguments': {'target_uuid': combat.TARGET, 'min_health': 14, 'timeout_ms': 1000},
            'policy': {'version': 1, 'execution_mode': 'request_only', 'reactions': 'stop'},
            'budgets': {'max_actions': 3, 'max_observations': 24, 'deadline_seconds': 10}, 'wait_ms': 0})
        self.assertIn('job_id', submitted, submitted)
        def finished():
            self.unknown_result = self.service.call('mdc_job', {'api_version': 'mdc.toolbox/1',
                'operation': 'status', 'job_id': submitted['job_id'], 'session_ref': submitted['session_ref']})
            return self.unknown_result['state'] not in ('accepted', 'running', 'stopping')
        self.until(finished)
        self.assertEqual(self.unknown_result['state'], 'unknown', self.unknown_result)
        self.assertIsNone(self.bridge.fixture_error)
        self.assertTrue(self.runtime.has_unresolved_execution)
        pending = self.runtime.pending_request_id
        owner = deepcopy(self.dog.owner)
        posts = deepcopy(self.bridge.posts)
        self.bridge.paused = self.bridge.screen_open = True
        args = {**self.ack_args(), 'pause_ref': '0' * 64}
        refused = self.service.call('mdc_job', args)
        self.assertEqual(refused['error']['code'], 'owner_busy', refused)
        self.assertFalse(self.backend.describe()['pause_acknowledgment']['eligible'])
        self.assertEqual(self.runtime.pending_request_id, pending)
        self.assertEqual(self.dog.owner, owner)
        self.assertEqual(self.bridge.posts, posts)
        self.assertEqual(len([p for p, _ in posts if p == '/control/scoped-action']), 1)
        self.assertFalse([p for p, _ in posts if p in ('/control/action/cancel', '/control/release-all')])
        self.assertEqual(list((self.root / 'watchdog' / 'results').glob('pause_*.json')), [])

    def test_active_lease_is_not_an_eligible_clean_pause(self):
        acquired = self.client.acquire_capability(self.owner, duration_ms=10000)
        self.assertEqual(acquired['status'], 'succeeded')
        original = deepcopy(self.dog.capability_lease)
        self.bridge.paused = self.bridge.screen_open = True
        result = self.service.call('mdc_job', {**self.ack_args(), 'pause_ref': '0' * 64})
        self.assertEqual(result['error']['code'], 'policy_violation', result)
        self.assertEqual(self.dog.capability_lease['owner_id'], original['owner_id'])
        self.assertFalse(self.backend.describe()['pause_acknowledgment']['eligible'])
        self.assertEqual(self.bridge.posts, [])

    def test_closed_public_schema_refuses_extra_fields_wrong_ack_and_types(self):
        args = self.pause()
        cases = [{**args, 'automatic_resume': True}, {**args, 'wait_ms': 0},
                 {**args, 'acknowledgment': 'resume_original_task'},
                 {**args, 'acknowledgment': 'release_authority_keep_original_effects_unknown_no_resume'},
                 {**args, 'pause_ref': True}, {**args, 'request_id': False},
                 {k: v for k, v in args.items() if k != 'acknowledgment'}]
        for value in cases:
            with self.subTest(value=value):
                result = self.service.call('mdc_job', value)
                self.assertEqual(result['error']['code'], 'invalid_request', result)
        self.assertEqual(list((self.root / 'watchdog' / 'results').glob('pause_*.json')), [])
        self.assertEqual(self.bridge.posts, [])
        self.assertFalse(self.dog.armed)

    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_actual_node_front_door_forwards_exact_ack_into_owner_chain(self):
        args = self.pause()
        epoch = self.dog.defense_epoch
        self.unpause()
        javascript = r'''
import {createInterface} from 'node:readline';
const {executeToolbox} = await import(process.argv[1]);
const lines = createInterface({input:process.stdin});
const iterator = lines[Symbol.asyncIterator]();
const args = JSON.parse((await iterator.next()).value);
let forwarded = 0;
const backend = {async call(name, value) {
  forwarded++; console.log(JSON.stringify({name, arguments:value}));
  return JSON.parse((await iterator.next()).value);
}};
const invalid = await executeToolbox('mdc_job', {...args, automatic_resume:true}, {backend});
if (invalid.error?.code !== 'invalid_request' || forwarded !== 0) throw Error('closed schema failed');
const before = JSON.stringify(args);
const result = await executeToolbox('mdc_job', args, {backend});
if (JSON.stringify(args) !== before || forwarded !== 1) throw Error('request changed or repeated');
console.log(JSON.stringify({result, forwarded, invalid}));
lines.close();
'''
        with subprocess.Popen([shutil.which('node'), '--input-type=module', '-e', javascript,
                               (SOURCE / 'client-mod/mcp/toolbox.mjs').as_uri()],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as child:
            child.stdin.write(json.dumps(args) + '\n')
            child.stdin.flush()
            forwarded = json.loads(child.stdout.readline())
            self.assertEqual(forwarded, {'name': 'mdc_job', 'arguments': args})
            result = self.service.call(forwarded['name'], forwarded['arguments'])
            stdout, stderr = child.communicate(json.dumps(result) + '\n', timeout=12)
            self.assertEqual(child.returncode, 0, stderr)
            node = json.loads(stdout)
            self.assertEqual(node['forwarded'], 1)
            self.assertEqual(node['result'], result)
            self.assert_success(result, args, epoch)


if __name__ == '__main__':
    unittest.main()
