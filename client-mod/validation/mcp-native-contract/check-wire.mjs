import assert from 'node:assert/strict';
import fs from 'node:fs';
import {clientActionTool,executeClientAction} from '../../mcp/client-action.mjs';

const wire=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const finite=clientActionTool.inputSchema.properties.body.properties.action.enum;
assert.deepEqual(wire.legacy_actions,[...finite,'recover_environment'].sort());
assert.deepEqual(wire.native_actions,[...wire.legacy_actions,'interact_block','use_item','select_hotbar','close_menu','attack_entity','shoot_entity','gateway_pearl','movement_budget_start','movement_budget_finish'].sort());
assert.equal(wire.cases.length,6);
for(const row of wire.cases) {
  const recovery=row.input.action==='recover_environment';
  const path=row.input.action==='follow_path';
  const accepted=recovery||(path&&row.input.timeout_ms===50);
  assert.equal(row.accepted,accepted);
  if(!accepted) {
    assert.equal(row.reason,path?'invalid_timeout_ms':'unsupported_action');
    continue;
  }
  assert.equal(row.timeout_ms,row.input.timeout_ms??0);
  assert.deepEqual(row.original,row.input);
  if(!recovery) continue;
  const session=row.running_receipt.action_session;
  const id=row.input.action_id;
  assert.equal(row.running_receipt.status,'running');
  assert.equal(row.running_receipt.action,'recover_environment');
  assert.equal(row.cancelled_receipt.status,'cancelled');
  assert.equal(row.cancelled_receipt.reason,'cancel_requested');
  assert.equal(row.cancelled_receipt.action_session,session);
  let touches=0;
  // validateRunId is read while constructing parse arguments; its invocation
  // itself is harmless. No descriptor, native request or input hook may run.
  const rejectHooks={validateRunId:x=>x,readDescriptor:()=>{touches++;throw new Error('descriptor access');}};
  await assert.rejects(executeClientAction({run_id:'wire-fixture',operation:'submit',expected_action_session:session,
    body:{...row.input,timeout_ms:row.input.timeout_ms??0,
      expected_action_session:session,expected_world_generation:session,expected_player_uuid:session}},rejectHooks),/action_unsupported/);
  assert.equal(touches,0);
  for(const operation of ['status','cancel']) {
    const calls=[];
    const receipt=operation==='status'?row.running_receipt:row.cancelled_receipt;
    const result=await executeClientAction({run_id:'wire-fixture',operation,action_id:id,expected_action_session:session},{
      validateRunId:x=>x,readDescriptor:async()=>({run_id:'wire-fixture',process_id:123,token:'synthetic-only'}),
      revalidateSession:async()=>({client_action:{action_session:session}}),
      assertInputIsolation:()=>assert.fail('status/cancel must not become new input submit'),
      requestJson:async(...args)=>{calls.push(args.slice(1));return structuredClone(receipt);},
      sanitizeForOutput:value=>value
    });
    assert.deepEqual(result.bridge,receipt);
    assert.deepEqual(calls,operation==='status'?[['GET','/control/action/status?action_id='+id,undefined]]:
      [['POST','/control/action/cancel',{action_id:id,expected_action_session:session}]]);
  }
}
console.log('MCP_NATIVE_WIRE_OK cases=6 recovery=default/zero/finite status/cancel=6 original-id-body=preserved unsupported-submit=zero-io');
