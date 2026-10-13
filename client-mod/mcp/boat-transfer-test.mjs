/** Exact native BoatTransferRequest codec parity. Injected hooks only; no game or sockets. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {clientActionTool,parseClientAction,executeClientAction} from './client-action.mjs';
const W='00000000-0000-0000-0000-000000000001', P='00000000-0000-0000-0000-000000000002';
const S='00000000-0000-0000-0000-000000000003', B='00000000-0000-0000-0000-000000000004';
const actions=['boat_mount','boat_dismount'];
const required=['action_id','action','boat_transfer_schema_version','timeout_ms','expected_world_generation',
  'expected_player_uuid','expected_action_session','expected_game_time','vehicle_uuid','vehicle_entity_id','vehicle_type'];
const body=(action='boat_mount')=>({action_id:'transfer-original-1',action,boat_transfer_schema_version:1,timeout_ms:2000,
  expected_world_generation:W,expected_player_uuid:P,expected_action_session:S,expected_game_time:100,
  vehicle_uuid:B,vehicle_entity_id:7,vehicle_type:'minecraft:boat'});
const args=b=>({run_id:'synthetic-boat-transfer',operation:'submit',expected_action_session:b.expected_action_session,body:b});
const nativeReceipt=(b,patch={})=>({ok:true,action_schema_version:1,action_id:b.action_id,action_session:S,
  action:b.action,status:'running',server_confirmed:false,result:{},...patch});
function hooks(result,overrides={}) {
  const calls=[];
  return {calls,readDescriptor:async()=>{calls.push('descriptor');return {run_id:'synthetic-boat-transfer',process_id:7,token:'synthetic'};},
    revalidateSession:async()=>({client_action:{action_session:S},world:{world_generation:W},player:{uuid:P}}),
    assertInputIsolation:()=>calls.push('isolation'),sanitizeForOutput:x=>x,
    requestJson:async(d,m,p,b)=>{calls.push({method:m,path:p,body:b});if(result instanceof Error)throw result;return structuredClone(result);},...overrides};
}
test('both boat-transfer variants expose exactly the native eleven required fields',()=>{
  const schema=clientActionTool.inputSchema.properties.body;
  for(const action of actions){
    const variant=schema.oneOf.find(v=>v.properties.action.const===action);
    assert.ok(variant);assert.equal(variant.additionalProperties,false);
    assert.deepEqual([...variant.required].sort(),[...required].sort());
    assert.deepEqual(Object.keys(variant.properties).sort(),[...required].sort());
    assert.deepEqual(variant.properties.timeout_ms,{type:'integer',minimum:1000,maximum:5000});
    assert.deepEqual(variant.properties.expected_game_time,{type:'integer',minimum:0,maximum:Number.MAX_SAFE_INTEGER});
    assert.deepEqual(variant.properties.vehicle_entity_id,{type:'integer',minimum:0,maximum:2147483647});
    assert.equal(variant.properties.boat_transfer_schema_version.const,1);
    assert.equal(variant.properties.vehicle_type.const,'minecraft:boat');
    for(const key of ['expected_world_generation','expected_player_uuid','expected_action_session','vehicle_uuid']){
      assert.equal(variant.properties[key].minLength,36);assert.equal(variant.properties[key].maxLength,36);
    }
  }
});
test('both transfer actions preserve every field, original ID and independent copy',()=>{
  for(const action of actions){
    const b=body(action), parsed=parseClientAction(args(b));
    assert.equal(parsed.endpoint,'/control/action');assert.equal(parsed.method,'POST');
    assert.equal(parsed.actionId,b.action_id);assert.deepEqual(parsed.body,b);assert.notEqual(parsed.body,b);
    parsed.body.vehicle_entity_id=99;assert.equal(b.vehicle_entity_id,7);
  }
});
test('every native transfer field is mandatory without default timeout or implicit binding',()=>{
  for(const action of actions)for(const key of required){
    const b=body(action);delete b[key];
    assert.throws(()=>parseClientAction({...args(body(action)),body:b}),`${action} missing ${key}`);
  }
});
test('transfer fields reject every other-action input including navigation and encounter flags',()=>{
  for(const action of actions)for(const key of ['boat_schema_version','water_surface_y','waypoints','expected_navigation_epoch','expected_origin',
    'sneak','jump','sprint','hotbar_slot','retry','renew','max_sneak_ticks','approach','shield','encounter_mode','encounter_scope',
    'encounter_pause_on_terminal','endpoint','token','plan','unknown']){
    for(const value of [false,null,0])assert.throws(()=>parseClientAction(args({...body(action),[key]:value})),`${action} extra ${key}`);
  }
});
test('transfer timeout accepts exactly integer 1000 through 5000ms endpoints',()=>{
  for(const action of actions){
    for(const timeout_ms of [1000,2000,5000])assert.equal(parseClientAction(args({...body(action),timeout_ms})).body.timeout_ms,timeout_ms);
    for(const timeout_ms of [-1,0,999,5001,120000,1000.5,NaN,Infinity,'2000',true,null])
      assert.throws(()=>parseClientAction(args({...body(action),timeout_ms})),`${action} timeout ${timeout_ms}`);
  }
});
test('transfer game-time freshness binding is a nonnegative safe integer only',()=>{
  for(const action of actions){
    for(const expected_game_time of [0,100,Number.MAX_SAFE_INTEGER])
      assert.equal(parseClientAction(args({...body(action),expected_game_time})).body.expected_game_time,expected_game_time);
    for(const expected_game_time of [-1,1.25,Number.MAX_SAFE_INTEGER+1,NaN,Infinity,'100',true,null])
      assert.throws(()=>parseClientAction(args({...body(action),expected_game_time})),`${action} tick ${expected_game_time}`);
  }
});
test('transfer vehicle IDs, ordinary boat type and schema reject coercion and unsupported values',()=>{
  for(const action of actions){
    for(const vehicle_entity_id of [0,2147483647])assert.equal(parseClientAction(args({...body(action),vehicle_entity_id})).body.vehicle_entity_id,vehicle_entity_id);
    for(const vehicle_entity_id of [-1,1.25,2147483648,NaN,Infinity,'7',true,null])assert.throws(()=>parseClientAction(args({...body(action),vehicle_entity_id})));
    for(const vehicle_type of ['minecraft:chest_boat','mod:boat','minecraft:pig','minecraft:boat\n',null,true])assert.throws(()=>parseClientAction(args({...body(action),vehicle_type})));
    for(const boat_transfer_schema_version of [0,2,1.5,'1',true,null])assert.throws(()=>parseClientAction(args({...body(action),boat_transfer_schema_version})));
  }
});
test('world player session and boat UUIDs require canonical lowercase UUIDs',()=>{
  for(const action of actions)for(const key of ['expected_world_generation','expected_player_uuid','expected_action_session','vehicle_uuid']){
    for(const value of ['',null,7,true,'not-a-uuid','1-1-1-1-1','A0000000-0000-0000-0000-000000000001',B+'\n',' '+B]){
      const b={...body(action),[key]:value};assert.throws(()=>parseClientAction(args(b)),`${action} ${key}: ${value}`);
    }
  }
  const b=body();assert.throws(()=>parseClientAction({...args(b),expected_action_session:W}),/session_mismatch/);
});
test('valid transfers each use one original-ID POST without extra controls or mutation of payload',async()=>{
  for(const action of actions){
    const b=body(action),h=hooks(nativeReceipt(b));const original=structuredClone(b);
    const result=await executeClientAction(args(b),h);
    assert.deepEqual(h.calls,['descriptor','isolation',{method:'POST',path:'/control/action',body:original}]);
    assert.deepEqual(b,original);assert.equal(result.bridge.action,b.action);assert.equal(result.bridge.server_confirmed,false);
  }
});
test('invalid transfer payload fails before descriptor lookup or any native operation',async()=>{
  for(const action of actions)for(const patch of [{expected_game_time:-1},{timeout_ms:5001},{retry:false},{expected_origin:{x:0,y:64,z:0}},{vehicle_type:'minecraft:chest_boat'}]){
    const b={...body(action),...patch},h=hooks(nativeReceipt(b));
    await assert.rejects(()=>executeClientAction(args(b),h));assert.deepEqual(h.calls,[]);
  }
});
test('changed world player or session refuses transfer before a native write',async()=>{
  for(const action of actions)for(const patch of [{world:{world_generation:P}},{player:{uuid:W}},{client_action:{action_session:W}}]){
    const b=body(action),h=hooks(nativeReceipt(b),{revalidateSession:async()=>({client_action:{action_session:S},world:{world_generation:W},player:{uuid:P},...patch})});
    await assert.rejects(()=>executeClientAction(args(b),h));assert.deepEqual(h.calls,['descriptor']);
  }
});
test('uncertain transfer POST or changed response never retries cancels or allocates another ID',async()=>{
  for(const action of actions){
    const b=body(action);
    for(const result of [new Error('timeout_after_send'),new Error('HTTP_409_busy'),null,{},nativeReceipt(b,{action_id:'changed'}),nativeReceipt(b,{action_session:W}),nativeReceipt(b,{action:action==='boat_mount'?'boat_dismount':'boat_mount'})]){
      const h=hooks(result);await assert.rejects(()=>executeClientAction(args(b),h),/outcome_unknown/);
      assert.deepEqual(h.calls,['descriptor','isolation',{method:'POST',path:'/control/action',body:b}]);
    }
  }
});
