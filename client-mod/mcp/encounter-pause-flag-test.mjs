/** Codecs and injected fake hooks only; no Minecraft, credentials or sockets. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {clientActionTool, parseClientAction, executeClientAction} from './client-action.mjs';
import {ENCOUNTER_MODE, validateEncounterRequest, validateEncounterReceipt} from './encounter-contract.mjs';
const FLAG='encounter_pause_on_terminal';
const U='00000000-0000-0000-0000-000000000001', V='00000000-0000-0000-0000-000000000002', W='00000000-0000-0000-0000-000000000003';
const body=()=>({action_id:'encounter-original-id',action:'combat_entity',timeout_ms:15000,
  expected_world_generation:U,expected_player_uuid:U,expected_action_session:U,
  target_uuid:V,target_entity_id:1,target_type:'minecraft:zombie',approach:false,shield:false,
  encounter_mode:ENCOUNTER_MODE,encounter_scope:[{entity_id:1,uuid:V,type:'minecraft:zombie'},{entity_id:2,uuid:W,type:'minecraft:zombie'}]});
const args=b=>({run_id:'synthetic',operation:'submit',expected_action_session:U,body:b});
function receipt(b,status='running'){
  const reason=status==='succeeded'?'encounter_clearance_observed':status==='running'?'accepted':'encounter_paused_risk_remaining';
  const e={encounter_schema_version:1,encounter_mode:ENCOUNTER_MODE,encounter_scope:structuredClone(b.encounter_scope),
    offense_disabled:true,risk_remaining:true,requires_handoff:true,safety_assured:false,danger_radius:8,
    outcome_scope:status==='succeeded'?'two_scoped_living_zombies_beyond_8_for_3_samples':null,
    clearance_observations:status==='succeeded'?3:0,
    scoped_living_threats:b.encounter_scope.map(x=>({...x,known:true,alive:true,clearance:9}))};
  if(status!=='running')Object.assign(e,{terminal_status:status,terminal_reason:reason});
  return {ok:true,action_schema_version:1,action_id:b.action_id,action_session:U,action:'combat_entity',status,reason,server_confirmed:false,
    result:{world_generation:U,input_release_confirmed:status!=='running',combat:{encounter:e,
      target_entity_id:b.target_entity_id,target_uuid:b.target_uuid,target_type:b.target_type,attack_dispatches:0,attack_completed:false,
      target_dead_observed:false,hits_confirmed:false,server_confirmed:false,risk_remaining:true,safety_assured:false}}};
}
function hooks(result){
  const calls=[];
  return {calls,readDescriptor:async()=>{calls.push('descriptor');return {run_id:'synthetic',process_id:7,token:'fake'};},
    revalidateSession:async()=>({client_action:{action_session:U},world:{world_generation:U},player:{uuid:U}}),
    assertInputIsolation:()=>{},sanitizeForOutput:x=>x,
    requestJson:async(d,m,p,b)=>{calls.push({method:m,path:p,body:b});return structuredClone(result);}};
}
function terminalHook(r,outcome='screen_installed'){
  return {hook_schema_version:1,requested:true,attempted:true,pause_call_attempted:outcome!=='rejected',outcome,
    pause_screen_installed:outcome==='screen_installed'?true:null,already_pause_screen:outcome==='screen_installed'?false:null,
    client_paused_observed:outcome==='screen_installed'?false:null,pause_effect_confirmed:false,server_confirmed:false,
    input_release_confirmed:r.result.input_release_confirmed};
}
test('flag schema is boolean and mode-conditioned only on combat variant',()=>{
  const schema=clientActionTool.inputSchema.properties.body;
  assert.equal(schema.properties[FLAG].type,'boolean');
  for(const variant of schema.oneOf){
    const isCombat=variant.properties.action.const==='combat_entity';
    assert.equal(Object.hasOwn(variant.properties,FLAG),isCombat);
    if(isCombat)assert.ok(variant.allOf[0].if.anyOf.some(c=>c.required.includes(FLAG)));
  }
});
test('true and false preserve exact cloned request, original ID and timeout',()=>{
  for(const value of [true,false]){
    const b={...body(),[FLAG]:value}, parsed=parseClientAction(args(b));
    assert.deepEqual(parsed.body,b);assert.equal(parsed.actionId,b.action_id);
    parsed.body.encounter_scope[0].entity_id=9;assert.equal(b.encounter_scope[0].entity_id,1);
  }
  const old=body();assert.deepEqual(parseClientAction(args(old)).body,old);
  assert.equal(Object.hasOwn(parseClientAction(args(old)).body,FLAG),false);
});
test('flag rejects coercion and hidden use without exact encounter mode including false',()=>{
  for(const value of [0,1,null,'true','false',[],{},undefined]){
    assert.throws(()=>validateEncounterRequest({...body(),[FLAG]:value}));
    assert.throws(()=>parseClientAction(args({...body(),[FLAG]:value})));
  }
  for(const value of [false,true]){
    const b={...body(),[FLAG]:value};delete b.encounter_mode;delete b.encounter_scope;
    assert.throws(()=>validateEncounterRequest(b));assert.throws(()=>parseClientAction(args(b)));
    for(const action of ['follow_path','boat_drive','click_slot'])assert.throws(()=>parseClientAction(args({...body(),action,[FLAG]:value})));
  }
});
test('true opt-in does not relax scope, input or timeout limits',()=>{
  for(const patch of [{timeout_ms:30001},{approach:true},{shield:true},{hotbar_slot:0},{encounter_scope:[]},{target_type:'minecraft:husk'},{encounter_mode:'other'}])
    assert.throws(()=>parseClientAction(args({...body(),[FLAG]:true,...patch})));
});
test('each true request requires true echo at running and every terminal status',()=>{
  const b={...body(),[FLAG]:true};
  for(const status of ['running','succeeded','failed','cancelled']){
    const r=receipt(b,status);if(status!=='running')r.result.encounter_terminal_pause=terminalHook(r);
    assert.throws(()=>validateEncounterReceipt(r,b));
    for(const value of [false,0,1,null,'true',[],{}]){r.result.combat.encounter[FLAG]=value;assert.throws(()=>validateEncounterReceipt(r,b));}
    r.result.combat.encounter[FLAG]=true;assert.doesNotThrow(()=>validateEncounterReceipt(r,b));
    assert.equal(Object.hasOwn(r.result.combat.encounter,'pause_effect_confirmed'),false);
  }
});
test('true terminal receipts require every typed hook field and cleanup identity',()=>{
  const b={...body(),[FLAG]:true};
  for(const status of ['succeeded','failed','cancelled']){
    const r=receipt(b,status);r.result.combat.encounter[FLAG]=true;
    assert.throws(()=>validateEncounterReceipt(r,b));
    const hook=terminalHook(r);
    for(const key of Object.keys(hook)){
      const invalid=structuredClone(r);invalid.result.encounter_terminal_pause={...hook};delete invalid.result.encounter_terminal_pause[key];
      assert.throws(()=>validateEncounterReceipt(invalid,b),`missing ${key}`);
    }
    for(const [key,value] of [['hook_schema_version',true],['hook_schema_version',2],['requested',false],['attempted',1],['pause_call_attempted',1],
      ['outcome','paused'],['pause_effect_confirmed',true],['server_confirmed',true],['pause_screen_installed','true'],['already_pause_screen',0],
      ['client_paused_observed',[]],['input_release_confirmed',false],['input_release_confirmed',1],['error_type',null],['reason',7],
      ['pause_call_attempted',false],['pause_screen_installed',false]]){
      const invalid=structuredClone(r);invalid.result.encounter_terminal_pause={...hook,[key]:value};
      assert.throws(()=>validateEncounterReceipt(invalid,b),`${key}: ${value}`);
    }
  }
});
test('installed rejected and unconfirmed hook outcomes preserve original terminal facts and risk',()=>{
  const b={...body(),[FLAG]:true};
  for(const status of ['succeeded','failed','cancelled'])for(const outcome of ['screen_installed','rejected','unconfirmed']){
    const r=receipt(b,status);r.result.combat.encounter[FLAG]=true;
    r.result.encounter_terminal_pause={...terminalHook(r,outcome),reason:'diagnostic',error_type:'SyntheticFailure'};
    const original=structuredClone(r);assert.doesNotThrow(()=>validateEncounterReceipt(r,b));assert.deepEqual(r,original);
    assert.equal(r.status,status);assert.equal(r.result.encounter_terminal_pause.pause_effect_confirmed,false);
  }
  const r=receipt(b,'failed');r.reason='input_release_unconfirmed';r.result.combat.encounter.terminal_reason=r.reason;
  r.result.input_release_confirmed=false;r.result.combat.encounter[FLAG]=true;r.result.encounter_terminal_pause=terminalHook(r,'unconfirmed');
  assert.doesNotThrow(()=>validateEncounterReceipt(r,b));
});
test('omitted and false requests retain old receipts and reject unrequested true echo',()=>{
  for(const b of [body(),{...body(),[FLAG]:false}])for(const status of ['running','succeeded','failed','cancelled']){
    const r=receipt(b,status);assert.doesNotThrow(()=>validateEncounterReceipt(r,b));
    r.result.combat.encounter[FLAG]=false;assert.doesNotThrow(()=>validateEncounterReceipt(r,b));
    r.result.combat.encounter[FLAG]=true;assert.throws(()=>validateEncounterReceipt(r,b));
  }
});
test('status without original request can inspect boolean echo without inventing authorization',()=>{
  const r=receipt(body());r.result.combat.encounter[FLAG]=true;
  assert.doesNotThrow(()=>validateEncounterReceipt(r));
  for(const value of [0,1,null,'true',[],{}]){r.result.combat.encounter[FLAG]=value;assert.throws(()=>validateEncounterReceipt(r));}
});
test('invalid hidden flag fails before descriptor or native requests',async()=>{
  const b=body();delete b.encounter_mode;delete b.encounter_scope;b[FLAG]=false;
  const h=hooks(receipt(body()));await assert.rejects(()=>executeClientAction(args(b),h));assert.deepEqual(h.calls,[]);
});
test('valid opt-in dispatches exactly once with original ID and exact body',async()=>{
  const b={...body(),[FLAG]:true},r=receipt(b,'succeeded');r.result.combat.encounter[FLAG]=true;
  r.result.encounter_terminal_pause=terminalHook(r);
  const h=hooks(r);const result=await executeClientAction(args(b),h);
  assert.deepEqual(h.calls,['descriptor',{method:'POST',path:'/control/action',body:b}]);
  assert.equal(result.bridge.action_id,b.action_id);assert.equal(result.bridge.server_confirmed,false);
});
test('missing echo after POST is unknown and never retried or replaced with cancellation',async()=>{
  const b={...body(),[FLAG]:true}, h=hooks(receipt(b,'succeeded'));
  await assert.rejects(()=>executeClientAction(args(b),h),e=>/outcome_unknown/.test(e.message)&&/pause_on_terminal_mismatch/.test(e.cause.message));
  assert.deepEqual(h.calls,['descriptor',{method:'POST',path:'/control/action',body:b}]);
});
