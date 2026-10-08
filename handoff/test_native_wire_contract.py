"""Focused Java HTTP codec -> resident mailbox -> harness contract audit.

Offline only: production pure Java classes, synthetic observations, temporary
queue files, no HTTP client/server or game. Requires an existing compiled native
classpath plus Gson; no dependency fetching/build environment provisioning.

MDC_NATIVE_CLASSPATH=<existing classes and Gson> JAVA_HOME=<existing JDK> \
    python3 handoff/test_native_wire_contract.py -v
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / 'candidates/encounter-stage1.1'
HARNESS = ROOT / 'test-tools/encounter-stage1.1-safety-v2'
sys.path[:0] = [str(CANDIDATE / 'resident-controller'), str(HARNESS)]
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from resident_controller.encounter_contract import validate_encounter_receipt as resident_validate
from encounter_contract import validate_encounter_receipt as harness_validate
from encounter_binding import EncounterBinding, resolve, summarize
from receipt_binding import terminal_signature

SESSION = '10000000-0000-4000-8000-000000000001'
NAMES = ('succeeded', 'failed', 'cancelled', 'cleanup_failed', 'callback_gap', 'missing_snapshot')
PRODUCERS = ('BridgeJson', 'ActionRegistry', 'ClientActionRequest',
             'BoundedCombatRequest', 'EncounterRequest', 'CombatInitialEvidence',
             'CombatHealthEvidence', 'BoundedEncounter')

JAVA = r'''
package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
public final class WireContractEmitter {
  static JsonObject decode(String json) { return JsonParser.parseString(json).getAsJsonObject(); }
  static String wire(JsonObject value) throws Exception { return BridgeJson.toJson(value); }
  public static void main(String[] args) throws Exception {
    JsonObject ids=decode(Files.readString(Path.of(args[0]))), output=new JsonObject();
    for(String name:ids.keySet()) {
      var registry=new ActionRegistry();var data=new JsonObject();
      data.addProperty("idle_wire",wire(registry.status(null)));
      JsonObject body=decode("""
        {"action":"combat_entity","timeout_ms":20000,
         "expected_world_generation":"00000000-0000-4000-8000-000000000001",
         "expected_player_uuid":"00000000-0000-4000-8000-000000000002",
         "target_uuid":"00000000-0000-4000-8000-000000000004","target_entity_id":4,
         "target_type":"minecraft:zombie","approach":false,"shield":false,
         "encounter_mode":"two_zombie_retreat_v1","encounter_scope":[
          {"entity_id":4,"uuid":"00000000-0000-4000-8000-000000000004","type":"minecraft:zombie"},
          {"entity_id":5,"uuid":"00000000-0000-4000-8000-000000000005","type":"minecraft:zombie"}]}
        """);
      body.addProperty("action_id",ids.get(name).getAsString());
      body.addProperty("expected_action_session",registry.session);
      var request=ClientActionRequest.parse(body);var parsed=BoundedCombatRequest.parse(body);
      var entry=registry.begin(request);entry.result.addProperty("world_generation",parsed.world());
      var combat=new JsonObject();entry.result.add("combat",combat);
      CombatInitialEvidence.initialize(parsed,combat,20,20);
      var clock=new AtomicLong(1_000_000_000L);var health=new CombatThreats.HealthGuard();
      var owner=new BoundedEncounter(parsed.encounter(),combat,0,64,0,30_000_000_000L,clock::get,health);
      data.addProperty("running_wire",wire(registry.status(request.id())));
      String terminal=null,reason=null;
      if(name.equals("callback_gap")) {
        reason=owner.callbackInterruption(1_150_000_001L,"pre_tick");terminal="failed";
      } else {
        for(int tick=0;tick<(name.equals("succeeded")||name.equals("cleanup_failed")?3:1);tick++) {
          clock.set(1_000_000_000L+tick*50_000_000L);entry.ticks=tick+1;
          var entities=List.of(
            new CombatThreats.Observed(4,"00000000-0000-4000-8000-000000000004","minecraft:zombie",0,64,10,.3,true,true),
            new CombatThreats.Observed(5,"00000000-0000-4000-8000-000000000005","minecraft:zombie",1,64,10,.3,true,true));
          var snapshot=name.equals("missing_snapshot")?null:new CombatThreats.Snapshot(entities,clock.get(),tick,name.equals("failed"),true);
          var step=owner.tick(tick,snapshot,new CombatRecovery.Motion(0,64,0,0,0,0,true),
            health.sample(tick,clock.get(),20),(a,b)->{throw new AssertionError("Movement unexpected");},()->null,(a,b)->{});
          terminal=step.terminal();reason=step.reason();
        }
      }
      if(name.equals("cancelled")) {terminal="cancelled";reason="cancel_requested";}
      boolean released=!name.equals("cleanup_failed");
      owner.terminal(released?terminal:"failed",released?reason:"input_release_unconfirmed");
      registry.finishAfterCleanup(terminal,reason,released);
      data.add("request",body);
      data.addProperty("terminal_wire",wire(registry.status(request.id())));
      var state=new JsonObject();state.add("client_action",registry.status(request.id()));
      data.addProperty("state_wire",wire(state));
      // input_owner describes the current global owner, not this retained entry.
      var next=body.deepCopy();next.addProperty("action_id",request.id()+"-later");
      registry.begin(ClientActionRequest.parse(next));
      data.addProperty("retained_wire",wire(registry.status(request.id())));
      data.addProperty("foreign_wire",wire(registry.status(null)));
      output.add(name,data);
    }
    System.out.println(output);
  }
}
'''


class WireBridge:
    """Feed actual Java HTTP JSON strings into real resident code without a socket."""
    base_url = 'http://127.0.0.1:1'

    def __init__(self, case, mode='normal'):
        self.case, self.mode, self.calls = case, mode, []
        self.action = json.loads(case['idle_wire'])
        self.accepted = False

    def state(self):
        b = self.case['request']
        return {'world': {'world_generation': b['expected_world_generation']},
                'player': {'uuid': b['expected_player_uuid'], 'health': 20,
                           'inventory': [], 'using_item': False, 'sprinting': False},
                'client_action': copy.deepcopy(self.action)}

    def observation(self):
        return {'state': self.state(), 'action': copy.deepcopy(self.action),
                'status': {'held_mappings': [], 'mouse': {'held_world_buttons': []}}}

    def request(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path == '/control/status':
            return {'protocol': 'mineclient-bridge', 'schema_version': 2,
                    'run_id': 'synthetic-wire-audit', 'process_id': 1, 'in_world': True,
                    **self.state()}
        if path == '/control/state?radius=8':
            return self.state()
        if path.startswith('/control/action/status'):
            return copy.deepcopy(self.action)
        if path == '/control/action':
            if payload != self.case['request']:
                raise AssertionError('resident native identity or request changed')
            if self.mode == 'rejected':
                raise BridgeError('encounter_stage1_disabled', status=409)
            self.accepted = True
            self.action = json.loads(self.case['running_wire'])
            if self.mode == 'unknown':
                raise BridgeError('transport_failed', uncertain=True)
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            if payload != {'action_id': self.case['request']['action_id'],
                           'expected_action_session': self.case['request']['expected_action_session']}:
                raise AssertionError('cancel binding changed')
            self.action = json.loads(self.case['terminal_wire'])
            return copy.deepcopy(self.action)
        raise AssertionError((method, path, payload))


class NativeWireContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cp = os.environ.get('MDC_NATIVE_CLASSPATH')
        if not cp:
            raise RuntimeError('Set MDC_NATIVE_CLASSPATH to existing native classes and Gson; no downloads are performed')
        cls.temp = tempfile.TemporaryDirectory(prefix='mdc-native-wire-')
        cls.addClassCleanup(cls.temp.cleanup)
        work = Path(cls.temp.name)
        java = work / 'WireContractEmitter.java'
        java.write_text(JAVA)
        ids = work / 'ids.json'
        ids.write_text(json.dumps({n: uuid.uuid5(uuid.UUID(SESSION), n + ':1').hex for n in NAMES}))
        main = CANDIDATE / 'client-mod/src/main/java/io/github/campione01/mineclientbridge'
        jdk = Path(os.environ['JAVA_HOME']) / 'bin'
        subprocess.run([str(jdk / 'javac'), '-cp', cp, '-d', str(work),
                        *(str(main / (name + '.java')) for name in PRODUCERS), str(java)], check=True)
        emitted = subprocess.run([str(jdk / 'java'), '-cp', str(work) + os.pathsep + cp,
                                  'io.github.campione01.mineclientbridge.WireContractEmitter', str(ids)],
                                 check=True, text=True, capture_output=True)
        cls.cases = json.loads(emitted.stdout)

    def exercise(self, name, mode='normal'):
        case = self.cases[name]
        temp = tempfile.TemporaryDirectory(prefix='mdc-wire-mailbox-')
        self.addCleanup(temp.cleanup)
        bridge = WireBridge(case, mode)
        resident = Resident(bridge, temp.name)
        resident.session_id = SESSION
        resident.start()
        self.addCleanup(resident.lock.close)
        queue = QueueClient(temp.name)
        body = {k: v for k, v in case['request'].items() if k != 'action_id'}
        binding = EncounterBinding(name, SESSION, body['expected_action_session'],
            body['expected_world_generation'], body['expected_player_uuid'],
            'combat_entity', encounter_request=body)
        before = bridge.observation()
        queue.submit({'op': 'action', **body}, request_id=name)
        resident.tick()
        running = []
        if mode == 'normal':
            running.append(copy.deepcopy(bridge.action))
            # Session publication is throttled; the last published queue owner
            # may still be pending immediately after this synthetic first tick.
            observed = queue.session()
            self.assertTrue(observed['active_request_id'] == name
                            or observed['pending_request_ids'] == [name])
            resident.publish()
            self.assertEqual(queue.session()['active_request_id'], name)
            self.assertEqual(queue.session()['active_action_id'], binding.expected_action_id)
            bridge.action = json.loads(case['terminal_wire'])
        for _ in range(4):
            if resident.active:
                resident.active.wake_at = 0
            resident.tick()
        result = queue.result(name)
        self.assertIsNotNone(result)
        self.assertEqual(sum(m == 'POST' and p == '/control/action' for m, p, _ in bridge.calls), 1)
        self.assertIs(result['risk_remaining'], True)
        self.assertIs(result['requires_handoff'], True)
        self.assertIs(result['safety_assured'], False)
        outcome = resolve(binding, result, before=before, after=bridge.observation(), running_evidence=running)
        return binding, result, outcome, bridge, resident, queue

    def test_actual_http_encoded_running_and_terminal_validate_in_both_consumers(self):
        reasons = {'succeeded': 'encounter_clearance_observed',
                   'failed': 'threat_snapshot_truncated_risk_remaining',
                   'cancelled': 'cancel_requested', 'cleanup_failed': 'input_release_unconfirmed',
                   'callback_gap': 'encounter_callback_observation_gap_risk_remaining',
                   'missing_snapshot': 'threat_snapshot_unknown_risk_remaining'}
        for name, case in self.cases.items():
            for stage in ('running_wire', 'terminal_wire', 'state_wire', 'retained_wire'):
                with self.subTest(name=name, stage=stage):
                    action = json.loads(case[stage])
                    if stage == 'state_wire':
                        action = action['client_action']
                    resident_validate(action, case['request'])
                    harness_validate(action, case['request'])
                    self.assertIn('outcome_scope', action['result']['combat']['encounter'])
                    self.assertEqual(action['action_id'], case['request']['action_id'])
                    if stage != 'running_wire':
                        self.assertEqual(action['reason'], reasons[name])

    def test_idle_native_ownership_has_explicit_null_on_actual_wire(self):
        for case in self.cases.values():
            action = json.loads(case['idle_wire'])
            self.assertIn('action_id', action)
            self.assertIsNone(action['action_id'])
            self.assertEqual(action['input_owner'], 'direct')

    def test_each_native_terminal_survives_real_resident_mailbox_and_harness(self):
        for name in NAMES:
            with self.subTest(name=name):
                binding, receipt, outcome, bridge, resident, queue = self.exercise(name)
                self.assertEqual(outcome['kind'], 'bound_terminal', outcome)
                self.assertEqual(receipt['status'], json.loads(self.cases[name]['terminal_wire'])['status'])
                self.assertIs(outcome['native_admission_confirmed'], True)
                summary = summarize(binding, outcome, bridge.observation())
                self.assertIs(summary['task_success'], False)
                self.assertEqual(summary['bounded_clearance_observed'], name == 'succeeded')
                self.assertEqual(sum(p == '/control/action/cancel' for _, p, _ in bridge.calls), 0)

    def test_null_admission_is_rejection_not_a_planned_id_or_retained_success(self):
        binding, receipt, outcome, bridge, resident, queue = self.exercise('succeeded', 'rejected')
        self.assertIn('action_id', receipt)
        self.assertIsNone(receipt['action_id'])
        self.assertEqual(outcome['kind'], 'admission_rejected', outcome)
        self.assertIs(outcome['native_admission_confirmed'], False)
        self.assertEqual(sum(p == '/control/action/cancel' for _, p, _ in bridge.calls), 0)

    def test_unknown_transport_keeps_unknown_even_with_valid_resolved_cancel(self):
        binding, receipt, outcome, bridge, resident, queue = self.exercise('cancelled', 'unknown')
        self.assertEqual(receipt['status'], 'uncertain')
        self.assertEqual(receipt['resolved_action']['status'], 'cancelled')
        self.assertEqual(outcome['kind'], 'unknown_post_outcome', outcome)
        self.assertIsNone(outcome['native_admission_confirmed'])
        self.assertTrue(resident.paused)
        self.assertEqual(sum(p == '/control/action/cancel' for _, p, _ in bridge.calls), 1)
        queue.submit({'op': 'action', **binding.encounter_request}, request_id=binding.request_id)
        resident.tick()
        self.assertEqual(sum(p == '/control/action' for _, p, _ in bridge.calls), 1)

    def test_global_input_owner_change_does_not_rebind_retained_terminal(self):
        for name, case in self.cases.items():
            with self.subTest(name=name):
                terminal, retained = (json.loads(case[k]) for k in ('terminal_wire', 'retained_wire'))
                self.assertEqual(terminal['input_owner'], 'direct')
                self.assertEqual(retained['input_owner'], 'action')
                self.assertEqual(terminal_signature(terminal), terminal_signature(retained))
                binding, receipt, outcome, bridge, resident, queue = self.exercise(name)
                bridge.action = retained
                self.assertEqual(resolve(binding, receipt, after=bridge.observation())['kind'], 'bound_terminal')
                bridge.action = json.loads(case['foreign_wire'])
                self.assertEqual(resolve(binding, receipt, after=bridge.observation())['kind'], 'identity_mismatch')

    def test_same_id_terminal_result_change_remains_a_conflict(self):
        binding, receipt, outcome, bridge, resident, queue = self.exercise('failed')
        bridge.action['result']['combat']['encounter']['clearance_observations'] = 1
        self.assertEqual(resolve(binding, receipt, after=bridge.observation())['kind'], 'receipt_conflict')


if __name__ == '__main__':
    unittest.main()
