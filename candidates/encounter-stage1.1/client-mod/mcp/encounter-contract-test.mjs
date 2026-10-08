import assert from 'node:assert/strict';
import {test} from 'node:test';
import {clientActionTool,parseClientAction,executeClientAction} from './client-action.mjs';
import {ENCOUNTER_MODE,validateEncounterReceipt} from './encounter-contract.mjs';
const U='00000000-0000-0000-0000-000000000001',V='00000000-0000-0000-0000-000000000002',W='00000000-0000-0000-0000-000000000003';
const outcome='two_scoped_living_zombies_beyond_8_for_3_samples';
const body=()=>({action_id:'encounter-1',action:'combat_entity',timeout_ms:15000,expected_world_generation:U,expected_player_uuid:U,expected_action_session:U,
  target_uuid:V,target_entity_id:1,target_type:'minecraft:zombie',approach:false,shield:false,encounter_mode:ENCOUNTER_MODE,
  encounter_scope:[{entity_id:1,uuid:V,type:'minecraft:zombie'},{entity_id:2,uuid:W,type:'minecraft:zombie'}]});
const args=(b=body())=>({run_id:'synthetic',operation:'submit',expected_action_session:U,body:b});
function receipt(b=body(),status='running',reason=status==='succeeded'?'encounter_clearance_observed':status==='running'?'accepted':'encounter_scope_missing_risk_remaining'){
  const e={encounter_schema_version:1,encounter_mode:ENCOUNTER_MODE,encounter_scope:structuredClone(b.encounter_scope),offense_disabled:true,risk_remaining:true,requires_handoff:true,safety_assured:false,
    outcome_scope:status==='succeeded'?outcome:null,clearance_observations:status==='succeeded'?3:0,danger_radius:8,
    scoped_living_threats:b.encounter_scope.map(x=>({...x,known:true,alive:true,clearance:9}))};
  if(status!=='running')Object.assign(e,{terminal_status:status,terminal_reason:reason});
  return {ok:true,action_schema_version:1,action_id:b.action_id,action_session:U,action:'combat_entity',status,reason,server_confirmed:false,
    result:{world_generation:U,input_release_confirmed:status!=='running',combat:{encounter:e,target_entity_id:b.target_entity_id,target_uuid:b.target_uuid,target_type:b.target_type,
      attack_dispatches:0,attack_completed:false,target_dead_observed:false,hits_confirmed:false,server_confirmed:false,risk_remaining:true,safety_assured:false}}};
}
function hooks(result=receipt()){
  const calls=[];return {calls,readDescriptor:async()=>{calls.push('descriptor');return {run_id:'synthetic',process_id:7,token:'fake'};},
    revalidateSession:async()=>({client_action:{action_session:U},world:{world_generation:U},player:{uuid:U}}),
    assertInputIsolation:()=>{},sanitizeForOutput:x=>x,
    requestJson:async(d,m,p,b)=>{calls.push({method:m,path:p,body:b});if(result instanceof Error)throw result;return structuredClone(result);}};
}
test('encounter request preserves exact immutable two-zombie scope',()=>{const b=body();const result=parseClientAction(args(b));assert.deepEqual(result.body,b);result.body.encounter_scope[0].entity_id=9;assert.equal(b.encounter_scope[0].entity_id,1);});
test('schema exposes closed cardinality, canonical UUID, mode and paired explicit options',()=>{
  const top=clientActionTool.inputSchema.properties.body;
  assert.equal(top.properties.encounter_mode.const,ENCOUNTER_MODE);
  assert.equal(top.properties.encounter_scope.minItems,2);assert.equal(top.properties.encounter_scope.maxItems,2);
  assert.equal(top.properties.encounter_scope.items.additionalProperties,false);
  const variant=top.oneOf.find(v=>v.properties.action.const==='combat_entity');
  assert.deepEqual(variant.allOf[0].then.required,['encounter_mode','encounter_scope','approach','shield']);
  for(const key of ['approach','shield'])assert.equal(variant.allOf[0].then.properties[key].const,false);
});
test('scope alone, unknown mode, null fields and non-combat operation rejected',()=>{
  const b=body();delete b.encounter_mode;
  for(const invalid of [b,{...body(),encounter_mode:null},{...body(),encounter_mode:'next'},{...body(),encounter_scope:null},{...body(),action:'follow_path'}])assert.throws(()=>parseClientAction(args(invalid)));
});
test('exact two unique ID and UUID bindings including original target',()=>{
  for(const scope of [[],body().encounter_scope.slice(0,1),[...body().encounter_scope,body().encounter_scope[0]],
    [body().encounter_scope[0],body().encounter_scope[0]],
    [body().encounter_scope[0],{...body().encounter_scope[1],entity_id:1}],
    [body().encounter_scope[0],{...body().encounter_scope[1],uuid:V}],
    [{...body().encounter_scope[0],uuid:U},body().encounter_scope[1]]])assert.throws(()=>parseClientAction(args({...body(),encounter_scope:scope})));
});
test('scope identity strict types reject boolean, fraction, overflow, alternate type and extra fields',()=>{
  for(const [key,value] of [['entity_id',true],['entity_id',1.5],['entity_id',-1],['entity_id',2147483648],['uuid','1-1-1-1-1'],['uuid','A0000000-0000-0000-0000-000000000001'],['type','minecraft:husk'],['extra',1]]){
    const b=body();b.encounter_scope[0][key]=value;assert.throws(()=>parseClientAction(args(b)),`${key}: ${value}`);
  }
});
test('forbidden input fields rejected even false; approach and shield explicitly false',()=>{
  for(const key of ['hotbar_slot','jump','sneak','sprint'])for(const value of [false,null,0])assert.throws(()=>parseClientAction(args({...body(),[key]:value})));
  for(const key of ['approach','shield']){const b=body();delete b[key];assert.throws(()=>parseClientAction(args(b)));for(const value of [true,0,'false'])assert.throws(()=>parseClientAction(args({...body(),[key]:value})));}
  assert.throws(()=>parseClientAction(args({...body(),target_type:'minecraft:husk'})));
});
test('invalid opt-in request fails before descriptor read or any bridge call',async()=>{
  const h=hooks();await assert.rejects(()=>executeClientAction(args({...body(),shield:true}),h));assert.deepEqual(h.calls,[]);
});
test('ordinary old combat remains unchanged without either new field',()=>{
  const b=body();delete b.encounter_mode;delete b.encounter_scope;Object.assign(b,{approach:true,shield:true,hotbar_slot:2,target_type:'minecraft:skeleton'});
  assert.deepEqual(parseClientAction(args(b)).body,b);
});
test('running failure cancellation and bounded success retain risk and handoff',()=>{
  for(const status of ['running','failed','cancelled','succeeded'])assert.doesNotThrow(()=>validateEncounterReceipt(receipt(body(),status),body()));
});
test('scope swapped or IDs reused cannot pass original action receipt binding',()=>{
  for(const mutate of [e=>e.encounter_scope.reverse(),e=>e.encounter_scope[0].uuid=U,e=>e.encounter_scope[0].entity_id=true]){
    const r=receipt(body(),'succeeded');mutate(r.result.combat.encounter);assert.throws(()=>validateEncounterReceipt(r,body()));
  }
});
test('three complete known living observations required for bounded success',()=>{
  for(const [key,value] of [['clearance_observations',2],['clearance_observations',true],['clearance_observations',4],['danger_radius',7.99],['outcome_scope',null],['scoped_living_threats',[]]]){
    const r=receipt(body(),'succeeded');r.result.combat.encounter[key]=value;assert.throws(()=>validateEncounterReceipt(r,body()));
  }
  for(const [key,value] of [['known',false],['alive',false],['clearance',8],['clearance',NaN],['clearance',Infinity],['clearance','9'],['uuid',U],['entity_id',true],['type','minecraft:skeleton']]){
    const r=receipt(body(),'succeeded');r.result.combat.encounter.scoped_living_threats[0][key]=value;assert.throws(()=>validateEncounterReceipt(r,body()));
  }
});
test('clearance never permits risk removed, no handoff, safety, attacks or dead target claims',()=>{
  for(const [key,value] of [['risk_remaining',false],['requires_handoff',false],['safety_assured',true],['offense_disabled',false],['terminal_status','failed'],['terminal_reason','path_reached']]){
    const r=receipt(body(),'succeeded');r.result.combat.encounter[key]=value;assert.throws(()=>validateEncounterReceipt(r,body()));
  }
  for(const [key,value] of [['attack_dispatches',1],['attack_dispatches',false],['attack_completed',true],['target_dead_observed',true],['hits_confirmed',true],['server_confirmed',true],['risk_remaining',false],['safety_assured',true],['target_entity_id',2]]){
    const r=receipt(body(),'succeeded');r.result.combat[key]=value;assert.throws(()=>validateEncounterReceipt(r,body()));
  }
});
test('missing encounter evidence or release confirmation cannot claim success',()=>{
  for(const mutate of [r=>delete r.result.combat.encounter,r=>r.result.input_release_confirmed=false,r=>r.server_confirmed=true,r=>delete r.result.combat.encounter.outcome_scope]){
    const r=receipt(body(),'succeeded');mutate(r);assert.throws(()=>validateEncounterReceipt(r,body()));
  }
  for(const reason of ['path_reached','target_dead_observed','retreat_segment_completed'])assert.throws(()=>validateEncounterReceipt(receipt(body(),'succeeded',reason),body()));
});
test('failed cancelled and running cannot retain stale previous success scope',()=>{
  for(const status of ['failed','cancelled','running']){const r=receipt(body(),status);r.result.combat.encounter.outcome_scope=outcome;assert.throws(()=>validateEncounterReceipt(r,body()));}
});
test('one submitted encounter is one POST with original ID and exact scope',async()=>{
  const h=hooks(receipt(body(),'succeeded'));const r=await executeClientAction(args(),h);
  assert.equal(r.bridge.status,'succeeded');assert.equal(r.bridge.result.combat.encounter.risk_remaining,true);
  assert.deepEqual(h.calls,['descriptor',{method:'POST',path:'/control/action',body:body()}]);
});
for(const failure of ['HTTP_409_encounter_stage1_disabled','timeout_after_acceptance','connection_reset_after_send'])test(failure+' produces one uncertain POST and never retries',async()=>{
  const h=hooks(new Error(failure));await assert.rejects(()=>executeClientAction(args(),h),/outcome_unknown/);
  assert.equal(h.calls.filter(x=>x.method==='POST').length,1);assert.equal(h.calls.length,2);
});
test('forged terminal clearance is uncertain and never resubmits or cancels',async()=>{
  const r=receipt(body(),'succeeded');r.result.combat.encounter.clearance_observations=2;
  const h=hooks(r);await assert.rejects(()=>executeClientAction(args(),h),e=>/outcome_unknown/.test(e.message)&&/encounter_receipt/.test(e.cause.message));
  assert.deepEqual(h.calls,['descriptor',{method:'POST',path:'/control/action',body:body()}]);
});
test('status receipt validates supplied encounter evidence without mutation or replay',async()=>{
  const r=receipt(body(),'succeeded');r.result.combat.encounter.scoped_living_threats[0].alive=false;
  const h=hooks(r);await assert.rejects(()=>executeClientAction({run_id:'synthetic',operation:'status',expected_action_session:U,action_id:'encounter-1'},h),e=>e.message.startsWith('encounter_receipt')&&!e.message.includes('outcome_unknown'));
  assert.deepEqual(h.calls,['descriptor',{method:'GET',path:'/control/action/status?action_id=encounter-1',body:undefined}]);
});

// Run terminal-pause codec regressions in the existing portable test command.
import "./encounter-pause-flag-test.mjs";
