import assert from 'node:assert/strict';
import {test} from 'node:test';
import {clientActionTool, parseClientAction, executeClientAction} from './client-action.mjs';
import {ENCOUNTER_MODE} from './encounter-contract.mjs';

// Fixed request/receipt fixtures adapted from next-readonly-v18's action and
// encounter tests. Exercise the production exports; no test-side validators.
const U = '00000000-0000-0000-0000-000000000001';
const V = '00000000-0000-0000-0000-000000000002';
const W = '00000000-0000-0000-0000-000000000003';
const actions = ['follow_path', 'break_block', 'place_block', 'click_slot',
  'combat_entity', 'boat_drive', 'boat_mount', 'boat_dismount'];
const common = {
  action_id: 'immutable-1', timeout_ms: 15000,
  expected_world_generation: U, expected_player_uuid: U, expected_action_session: U
};
const walk = () => ({...common, action: 'follow_path',
  waypoints: [{x: 0, y: 64, z: 2}], expected_navigation_epoch: 3,
  expected_origin: {x: 0, y: 64, z: 0}, sprint: false});
const submit = body => ({run_id: 'synthetic', operation: 'submit',
  expected_action_session: U, body});
const inspect = (operation, action_id = common.action_id) => ({
  run_id: 'synthetic', operation, expected_action_session: U, action_id
});
const current = () => ({client_action: {action_session: U},
  world: {world_generation: U}, player: {uuid: U}});
const receipt = (body = walk(), patch = {}) => ({
  ok: true, action_schema_version: 1, action_session: U,
  action_id: body.action_id, action: body.action, status: 'running',
  reason: 'accepted', server_confirmed: false, ...patch
});
function nativeBodies() {
  const boat = {vehicle_uuid: V, vehicle_entity_id: 7, vehicle_type: 'minecraft:boat'};
  return [
    walk(),
    {...common, action: 'break_block', target: {x: 0, y: 64, z: 1}},
    {...common, action: 'place_block', support: {x: 0, y: 63, z: 1}, face: 'up'},
    {...common, action: 'click_slot', container_id: 0, slot: 9, button: 0, click_type: 'pickup'},
    {...common, action: 'combat_entity', target_uuid: V, target_entity_id: 1,
      target_type: 'minecraft:zombie', approach: true, shield: true},
    {...common, ...boat, action: 'boat_drive', timeout_ms: 10000,
      boat_schema_version: 1, water_surface_y: 63, waypoints: [{x: 0, z: 8}, {x: 0, z: 16}]},
    ...['boat_mount', 'boat_dismount'].map(action => ({...common, ...boat, action,
      timeout_ms: 5000, boat_transfer_schema_version: 1, expected_game_time: 42}))
  ];
}
function encounterBody() {
  return {...common, action_id: 'encounter-1', action: 'combat_entity',
    target_uuid: V, target_entity_id: 1, target_type: 'minecraft:zombie',
    approach: false, shield: false, encounter_mode: ENCOUNTER_MODE,
    encounter_pause_on_terminal: true,
    encounter_scope: [{entity_id: 1, uuid: V, type: 'minecraft:zombie'},
      {entity_id: 2, uuid: W, type: 'minecraft:zombie'}]};
}
function encounterReceipt(body, status, released = true) {
  const reason = status === 'succeeded' ? 'encounter_clearance_observed'
    : released ? 'encounter_scope_missing_risk_remaining' : 'input_release_unconfirmed';
  const encounter = {
    encounter_schema_version: 1, encounter_mode: ENCOUNTER_MODE,
    encounter_scope: structuredClone(body.encounter_scope), encounter_pause_on_terminal: true,
    offense_disabled: true, risk_remaining: true, requires_handoff: true, safety_assured: false,
    outcome_scope: status === 'succeeded' ? 'two_scoped_living_zombies_beyond_8_for_3_samples' : null,
    clearance_observations: status === 'succeeded' ? 3 : 0, danger_radius: 8,
    terminal_status: status, terminal_reason: reason,
    scoped_living_threats: body.encounter_scope.map(x => ({...x, known: true, alive: true, clearance: 9}))
  };
  return receipt(body, {status, reason, result: {
    world_generation: U, input_release_confirmed: released,
    encounter_terminal_pause: {hook_schema_version: 1, requested: true, attempted: true,
      pause_call_attempted: false, outcome: 'unconfirmed', pause_effect_confirmed: false,
      server_confirmed: false, pause_screen_installed: null, already_pause_screen: null,
      client_paused_observed: null, input_release_confirmed: released},
    combat: {encounter, target_entity_id: body.target_entity_id, target_uuid: body.target_uuid,
      target_type: body.target_type, attack_dispatches: 0, attack_completed: false,
      target_dead_observed: false, hits_confirmed: false, server_confirmed: false,
      risk_remaining: true, safety_assured: false}
  }});
}
function fixture(options = {}) {
  const events = [], requests = [];
  const descriptor = {run_id: 'synthetic', process_id: 7, token: 'fixture-token'};
  const hooks = {
    readDescriptor: async runId => {
      events.push('descriptor');
      assert.equal(runId, descriptor.run_id);
      return descriptor;
    },
    revalidateSession: async actual => {
      events.push('current');
      assert.equal(actual, descriptor);
      if (options.statusError) throw options.statusError;
      return options.current ?? current();
    },
    assertInputIsolation: (actual, status) => {
      events.push('isolation');
      assert.equal(actual, descriptor);
      assert.deepEqual(status, options.current ?? current());
      if (options.isolationError) throw options.isolationError;
    },
    requestJson: async (actual, method, path, body) => {
      events.push('request');
      assert.equal(actual, descriptor);
      requests.push({method, path, body: structuredClone(body)});
      if (options.requestError) throw options.requestError;
      return structuredClone(Object.hasOwn(options, 'response') ? options.response : receipt(body));
    },
    sanitizeForOutput: (result, token) => {
      events.push('sanitize');
      assert.equal(token, descriptor.token);
      return structuredClone(result);
    }
  };
  return {hooks, events, requests};
}
const oneSubmit = body => [{method: 'POST', path: '/control/action', body}];
const unknown = error => /outcome_unknown/.test(error.message);

test('bounded schema and parser retain exactly eight native actions and every finite request', () => {
  const schema = clientActionTool.inputSchema;
  assert.equal(clientActionTool.name, 'minecraft_client_action');
  assert.equal(schema.type, 'object');
  for (const key of ['oneOf', 'anyOf', 'allOf']) assert.equal(schema[key], undefined);
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.properties.operation.enum, ['submit', 'status', 'cancel']);
  assert.deepEqual(schema.properties.body.properties.action.enum, actions);
  assert.deepEqual(schema.properties.body.oneOf.map(v => v.properties.action.const), actions);
  for (const variant of schema.properties.body.oneOf) {
    assert.equal(variant.additionalProperties, false);
    assert.ok(variant.properties.timeout_ms.minimum > 0);
    for (const key of ['action_id', 'action', 'timeout_ms', 'expected_world_generation',
      'expected_player_uuid', 'expected_action_session']) assert.ok(variant.required.includes(key));
  }
  for (const body of nativeBodies()) {
    const parsed = parseClientAction(submit(body));
    assert.deepEqual(parsed.body, body, body.action);
    assert.notEqual(parsed.body, body);
    assert.equal(parsed.actionId, body.action_id);
    assert.equal(parsed.body.timeout_ms, body.timeout_ms);
  }
});

test('unsupported and recovery actions, zero leases, half bindings and malformed operations have zero hook I/O', async () => {
  const noOrigin = walk(), noEpoch = walk();
  delete noOrigin.expected_origin;
  delete noEpoch.expected_navigation_epoch;
  const invalid = [
    ...['draft_plan', 'unknown_action', 'toString', '__proto__'].map(action => [submit({...walk(), action}), /action_unsupported/]),
    ...[0, 15000].map(timeout_ms => [submit({...walk(), action: 'recover_environment', timeout_ms}), /action_unsupported/]),
    [submit({...walk(), timeout_ms: 0}), /action_invalid_number/],
    [submit(noOrigin), /action_navigation_binding_pair_required/],
    [submit(noEpoch), /action_navigation_binding_pair_required/],
    [submit({...walk(), endpoint: '/control/input/release_all'}), /action_unknown_field/],
    [submit({...walk(), expected_action_session: V}), /action_session_mismatch/],
    ...['expected_world_generation', 'expected_player_uuid', 'expected_action_session']
      .map(key => [submit({...walk(), [key]: 'invalid-uuid'}), /action_invalid_uuid/]),
    ...['status', 'cancel'].flatMap(operation => [
      [{run_id: 'synthetic', operation, expected_action_session: U}, /action_id_required_without_body/],
      [{...inspect(operation), body: walk()}, /action_id_required_without_body/],
      [inspect(operation, '../latest'), /action_id_required_without_body/]
    ])
  ];
  for (const [args, expected] of invalid) {
    const before = structuredClone(args), f = fixture();
    assert.throws(() => parseClientAction(args), expected);
    await assert.rejects(() => executeClientAction(args, f.hooks), expected);
    assert.deepEqual(f.events, [], JSON.stringify(args));
    assert.deepEqual(f.requests, []);
    assert.deepEqual(args, before);
  }
});

test('each supported submit revalidates first and sends its exact immutable body once', async () => {
  for (const body of nativeBodies()) {
    const before = structuredClone(body), f = fixture();
    const result = await executeClientAction(submit(body), f.hooks);
    assert.deepEqual(f.events, ['descriptor', 'current', 'isolation', 'request', 'sanitize']);
    assert.deepEqual(f.requests, oneSubmit(before));
    assert.deepEqual(body, before);
    assert.deepEqual(result, {run_id: 'synthetic', process_id: 7,
      operation: 'submit', bridge: receipt(before)});
  }
});

test('all three changed or missing identities, failed status reads and input isolation fail before POST', async () => {
  for (const [section, key, reason] of [
    ['client_action', 'action_session', 'action_session_changed'],
    ['world', 'world_generation', 'action_world_changed'],
    ['player', 'uuid', 'action_player_changed']
  ]) {
    for (const missing of [false, true]) {
      const status = current();
      if (missing) delete status[section][key]; else status[section][key] = V;
      const f = fixture({current: status});
      await assert.rejects(() => executeClientAction(submit(walk()), f.hooks), {message: reason});
      assert.deepEqual(f.events, ['descriptor', 'current']);
      assert.deepEqual(f.requests, []);
    }
  }
  for (const [options, events] of [
    [{statusError: Error('current_status_unavailable')}, ['descriptor', 'current']],
    [{isolationError: Error('external_owner_active')}, ['descriptor', 'current', 'isolation']]
  ]) {
    const f = fixture(options);
    await assert.rejects(() => executeClientAction(submit(walk()), f.hooks),
      error => error === (options.statusError ?? options.isolationError) && !unknown(error));
    assert.deepEqual(f.events, events);
    assert.deepEqual(f.requests, []);
  }
});

test('unknown POST outcomes and malformed successes never retry, rename, cancel or release inputs', async () => {
  const body = walk(), before = structuredClone(body);
  const options = [
    ...['timeout_after_acceptance', 'connection_reset_after_send', 'HTTP_409_busy', 'malformed_response']
      .map(reason => ({requestError: Error(reason)})),
    ...[null, {}, receipt(body, {action_session: V}), receipt(body, {action_id: 'replacement-id'}),
      receipt(body, {action_schema_version: 2}), receipt(body, {status: 'idle'}),
      receipt(body, {ok: false}), receipt(body, {action: 'boat_drive'})].map(response => ({response}))
  ];
  for (const option of options) {
    const f = fixture(option);
    await assert.rejects(() => executeClientAction(submit(body), f.hooks), error =>
      unknown(error) && (option.requestError ? error.cause === option.requestError
        : error.cause.message.startsWith('action_response_')));
    assert.deepEqual(f.events, ['descriptor', 'current', 'isolation', 'request']);
    assert.deepEqual(f.requests, oneSubmit(before));
    assert.deepEqual(body, before);
  }
});

test('status and cancel can inspect a known root recovery ID without exposing recovery submission', async () => {
  const action_id = 'root-recovery:01';
  for (const operation of ['status', 'cancel']) {
    const response = receipt({action_id, action: 'recover_environment'}, {
      status: 'cancelled', reason: 'cancelled_by_request', result: {environment_waiting_for_route: true}
    });
    const f = fixture({response});
    const result = await executeClientAction(inspect(operation, action_id), f.hooks);
    assert.deepEqual(f.events, ['descriptor', 'current', 'request', 'sanitize']);
    assert.deepEqual(f.requests, operation === 'status'
      ? [{method: 'GET', path: '/control/action/status?action_id=root-recovery%3A01', body: undefined}]
      : [{method: 'POST', path: '/control/action/cancel', body: {action_id, expected_action_session: U}}]);
    assert.deepEqual(result.bridge, response);
    assert.equal(result.bridge.action, 'recover_environment');
    assert.equal(Object.hasOwn(result.bridge.result, 'input_release_confirmed'), false);
  }
});

test('status/cancel recheck the current session; GET races stay read errors and uncertain cancel stays one POST', async () => {
  for (const operation of ['status', 'cancel']) {
    const status = current();
    status.client_action.action_session = V;
    const stale = fixture({current: status});
    await assert.rejects(() => executeClientAction(inspect(operation), stale.hooks),
      {message: 'action_session_changed'});
    assert.deepEqual(stale.events, ['descriptor', 'current']);
    assert.deepEqual(stale.requests, []);

    for (const response of [null, {}, receipt(walk(), {action_session: V}),
      receipt(walk(), {action_id: 'wrong-id'}), receipt(walk(), {action_schema_version: 2})]) {
      const f = fixture({response});
      await assert.rejects(() => executeClientAction(inspect(operation), f.hooks), error =>
        operation === 'status' ? !unknown(error) && error.message.startsWith('action_response_')
          : unknown(error) && error.cause.message.startsWith('action_response_'));
      assert.deepEqual(f.events, ['descriptor', 'current', 'request']);
      assert.deepEqual(f.requests, operation === 'status'
        ? [{method: 'GET', path: '/control/action/status?action_id=immutable-1', body: undefined}]
        : [{method: 'POST', path: '/control/action/cancel', body: {action_id: 'immutable-1', expected_action_session: U}}]);
    }
  }
});

test('ordinary terminal receipts preserve native release evidence and diagnostics without synthesizing claims', async () => {
  const body = walk();
  for (const [status, reason, result] of [
    ['succeeded', 'path_reached', {world_generation: U, input_release_confirmed: true}],
    ['cancelled', 'cancelled_by_request', {world_generation: U, input_release_confirmed: true}],
    ['failed', 'input_release_unconfirmed', {world_generation: U, input_release_confirmed: false,
      requested_terminal_status: 'succeeded', requested_terminal_reason: 'path_reached'}],
    ['failed', 'world_changed', {world_generation: U}]
  ]) {
    const response = receipt(body, {status, reason, result});
    for (const operation of ['submit', 'status', 'cancel']) {
      const f = fixture({response});
      const output = await executeClientAction(operation === 'submit' ? submit(body) : inspect(operation), f.hooks);
      assert.deepEqual(output.bridge, response);
      assert.equal(f.requests.length, 1);
      assert.equal(output.bridge.server_confirmed, false);
      assert.equal(Object.hasOwn(output.bridge.result, 'input_release_confirmed'),
        Object.hasOwn(result, 'input_release_confirmed'));
    }
  }
});

test('encounter terminals preserve raw handoff, release and unconfirmed pause; forged success stays one uncertain POST', async () => {
  const body = encounterBody();
  assert.deepEqual(parseClientAction(submit(body)).body, body);
  for (const [status, released] of [['succeeded', true], ['cancelled', true], ['failed', false]]) {
    const response = encounterReceipt(body, status, released);
    for (const operation of ['submit', 'status', 'cancel']) {
      const f = fixture({response});
      const result = await executeClientAction(operation === 'submit' ? submit(body)
        : inspect(operation, body.action_id), f.hooks);
      assert.deepEqual(result.bridge, response);
      assert.equal(f.requests.length, 1);
      assert.equal(result.bridge.result.input_release_confirmed, released);
      assert.equal(result.bridge.result.combat.encounter.requires_handoff, true);
      assert.equal(result.bridge.result.combat.encounter.risk_remaining, true);
      assert.equal(result.bridge.result.encounter_terminal_pause.pause_effect_confirmed, false);
    }
  }
  for (const mutate of [
    r => { r.result.combat.encounter.requires_handoff = false; },
    r => { r.result.combat.encounter.clearance_observations = 2; },
    r => { r.result.input_release_confirmed = false; },
    r => { r.result.encounter_terminal_pause.pause_effect_confirmed = true; }
  ]) {
    const response = encounterReceipt(body, 'succeeded');
    mutate(response);
    const f = fixture({response});
    await assert.rejects(() => executeClientAction(submit(body), f.hooks), error =>
      unknown(error) && error.cause.message.startsWith('encounter_receipt_'));
    assert.deepEqual(f.events, ['descriptor', 'current', 'isolation', 'request']);
    assert.deepEqual(f.requests, oneSubmit(body));
  }
});
