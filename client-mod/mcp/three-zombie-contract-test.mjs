import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseClientAction,executeClientAction} from './client-action.mjs';
import {ENCOUNTER_MODE,THREE_ENCOUNTER_MODE,validateEncounterReceipt} from './encounter-contract.mjs';
const uu=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope=()=>[1,2,3].map(n=>({entity_id:n,uuid:uu(n),type:'minecraft:zombie'}));
const body=()=>({action_id:'three-test',action:'combat_entity',timeout_ms:15000,expected_world_generation:uu(9),expected_player_uuid:uu(9),expected_action_session:uu(9),target_uuid:uu(1),target_entity_id:1,target_type:'minecraft:zombie',approach:false,shield:false,encounter_mode:THREE_ENCOUNTER_MODE,encounter_scope:scope()});
const args=(b=body())=>({run_id:'synthetic',operation:'submit',expected_action_session:uu(9),body:b});
function receipt(b=body(),status='succeeded'){
  const e={encounter_schema_version:1,encounter_mode:b.encounter_mode,encounter_scope:structuredClone(b.encounter_scope),offense_disabled:true,risk_remaining:true,requires_handoff:true,safety_assured:false,danger_radius:8,clearance_observations:status==='succeeded'?3:0,outcome_scope:status==='succeeded'?'three_scoped_living_zombies_beyond_8_for_3_samples':null,
    projectile_observation:{known:true,count:0,policy:'any_loaded_projectile_refuses',scope:'client_loaded_projectiles_within_16_not_server_complete'},scoped_living_threats:b.encounter_scope.map(x=>({...x,known:true,alive:true,clearance:9}))};
  const reason=status==='succeeded'?'encounter_clearance_observed':status==='running'?'accepted':'encounter_projectile_observed_risk_remaining';
  if(status!=='running')Object.assign(e,{terminal_status:status,terminal_reason:reason});
  return {ok:true,action_schema_version:1,action_id:b.action_id,action_session:uu(9),action:'combat_entity',status,reason,server_confirmed:false,result:{world_generation:uu(9),input_release_confirmed:status!=='running',combat:{encounter:e,target_entity_id:b.target_entity_id,target_uuid:b.target_uuid,target_type:b.target_type,attack_dispatches:0,attack_completed:false,target_dead_observed:false,hits_confirmed:false,server_confirmed:false,risk_remaining:true,safety_assured:false}}};
}
function hooks(result=receipt()){
  const calls=[];return {calls,readDescriptor:async()=>({run_id:'synthetic',process_id:7,token:'fake'}),revalidateSession:async()=>({client_action:{action_session:uu(9)},world:{world_generation:uu(9)},player:{uuid:uu(9)}}),assertInputIsolation:()=>{},sanitizeForOutput:x=>x,requestJson:async(d,m,p,b)=>{calls.push({method:m,path:p,body:b});if(result instanceof Error)throw result;return structuredClone(result);}};
}
test('three mode remains exact and cannot silently expand old two mode',()=>{
  assert.deepEqual(parseClientAction(args()).body,body());
  assert.throws(()=>parseClientAction(args({...body(),encounter_mode:ENCOUNTER_MODE})));
  assert.throws(()=>parseClientAction(args({...body(),encounter_scope:scope().slice(0,2)})));
  const b=body();b.encounter_scope[2].type='minecraft:skeleton';assert.throws(()=>parseClientAction(args(b)));
});
test('third identity and target binding cannot be reused or replaced',()=>{
  for(const [k,v] of [['entity_id',1],['entity_id',2],['uuid',uu(2)],['type','minecraft:husk'],['extra',1]]){const b=body();b.encounter_scope[2][k]=v;assert.throws(()=>parseClientAction(args(b)));}
  assert.throws(()=>parseClientAction(args({...body(),target_uuid:uu(99)})));
});
test('all new mode statuses are exact bound observations with risk',()=>{for(const status of ['running','failed','cancelled','succeeded'])validateEncounterReceipt(receipt(body(),status),body());});
test('mode and ordered scope cannot be swapped across receipt',()=>{
  for(const mutate of [e=>e.encounter_mode=ENCOUNTER_MODE,e=>e.encounter_scope.reverse(),e=>e.encounter_scope.pop(),e=>e.outcome_scope='two_scoped_living_zombies_beyond_8_for_3_samples']){const r=receipt();mutate(r.result.combat.encounter);assert.throws(()=>validateEncounterReceipt(r,body()));}
});
test('three living proof and known zero projectiles required for success',()=>{
  for(const [k,v] of [['known',false],['count',null],['count',false],['count',1],['count',-1],['policy','arrow_safe'],['scope','global']]){const r=receipt();r.result.combat.encounter.projectile_observation[k]=v;assert.throws(()=>validateEncounterReceipt(r,body()));}
  for(const mutate of [e=>delete e.projectile_observation,e=>e.scoped_living_threats.pop(),e=>e.scoped_living_threats[2].alive=false,e=>e.scoped_living_threats[2].clearance=8]){const r=receipt();mutate(r.result.combat.encounter);assert.throws(()=>validateEncounterReceipt(r,body()));}
});
test('new mode still forbids every added input and accepts no off-scope attack',()=>{for(const change of [{approach:true},{shield:true},{jump:false},{sprint:false},{hotbar_slot:0}])assert.throws(()=>parseClientAction(args({...body(),...change})));});
test('new mode one exact POST and no retry after unknown or new gate rejection',async()=>{
  const h=hooks();await executeClientAction(args(),h);assert.deepEqual(h.calls,[{method:'POST',path:'/control/action',body:body()}]);
  for(const message of ['timeout_after_acceptance','HTTP_409_encounter_three_zombie_disabled']){const x=hooks(new Error(message));await assert.rejects(()=>executeClientAction(args(),x),/outcome_unknown/);assert.equal(x.calls.length,1);}
});
test('stateless status can validate new mode but not infer submitted scope',()=>{assert.doesNotThrow(()=>validateEncounterReceipt(receipt()));const r=receipt();r.result.combat.encounter.scoped_living_threats[2].uuid=uu(99);assert.throws(()=>validateEncounterReceipt(r));});
