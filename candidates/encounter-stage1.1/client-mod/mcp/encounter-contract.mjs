/** Optional stage-1 wire validation only; no inputs, transport, retry or feature enablement. */
export const ENCOUNTER_MODE = 'two_zombie_retreat_v1';
const OUTCOME = 'two_scoped_living_zombies_beyond_8_for_3_samples';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const identityKeys = ['entity_id', 'uuid', 'type'];
export const encounterScopeSchema = {type:'array', minItems:2, maxItems:2, uniqueItems:true,
  items:{type:'object', properties:{entity_id:{type:'integer',minimum:0,maximum:2147483647},
    uuid:{type:'string',pattern:UUID.source},type:{type:'string',const:'minecraft:zombie'}},
    required:identityKeys,additionalProperties:false}};
export const encounterCondition = {
  if:{anyOf:[{required:['encounter_mode']},{required:['encounter_scope']},{required:['encounter_pause_on_terminal']}]},
  then:{required:['encounter_mode','encounter_scope','approach','shield'],
    properties:{approach:{const:false},shield:{const:false},target_type:{const:'minecraft:zombie'}},
    not:{anyOf:['hotbar_slot','jump','sneak','sprint'].map(k=>({required:[k]}))}}
};
function require(ok, reason) {if(!ok) throw new Error(reason);}
function object(x) {return x!==null && typeof x==='object' && !Array.isArray(x) && Object.getPrototypeOf(x)===Object.prototype;}
function integer(x,lo=0,hi=2147483647) {return Number.isInteger(x) && x>=lo && x<=hi;}
function sameIdentity(a,b) {return identityKeys.every(k=>a[k]===b[k]);}
function identity(x) {require(object(x) && Object.keys(x).length===3 && identityKeys.every(k=>Object.hasOwn(x,k)) && integer(x.entity_id) && typeof x.uuid==='string' && UUID.test(x.uuid) && x.type==='minecraft:zombie','encounter_scope_identity_invalid');}
function scope(x) {require(Array.isArray(x)&&x.length===2,'encounter_scope_requires_two');x.forEach(identity);require(x[0].entity_id!==x[1].entity_id&&x[0].uuid!==x[1].uuid,'encounter_scope_identity_duplicate');}
export function validateEncounterRequest(body) {
  if(!['encounter_mode','encounter_scope','encounter_pause_on_terminal'].some(k=>Object.hasOwn(body,k)))return false;
  require(body.action==='combat_entity'&&body.encounter_mode===ENCOUNTER_MODE,'encounter_mode_invalid');
  if(Object.hasOwn(body,'encounter_pause_on_terminal'))require(typeof body.encounter_pause_on_terminal==='boolean','encounter_pause_on_terminal_requires_boolean');
  require(body.target_type==='minecraft:zombie'&&body.approach===false&&body.shield===false,'encounter_requires_zombie_no_approach_no_shield');
  require(!['hotbar_slot','jump','sneak','sprint'].some(k=>Object.hasOwn(body,k)),'encounter_forbidden_input_field');
  scope(body.encounter_scope);
  require(body.encounter_scope.some(x=>x.entity_id===body.target_entity_id&&x.uuid===body.target_uuid&&x.type===body.target_type),'encounter_scope_target_missing');
  return true;
}
function validateTerminalPause(result) {
  const p=result.encounter_terminal_pause;
  require(object(p)&&p.hook_schema_version===1&&p.requested===true&&p.attempted===true
    &&typeof p.pause_call_attempted==='boolean'&&['screen_installed','rejected','unconfirmed'].includes(p.outcome)
    &&p.pause_effect_confirmed===false&&p.server_confirmed===false,'encounter_receipt_terminal_pause_invalid');
  for(const k of ['pause_screen_installed','already_pause_screen','client_paused_observed'])
    require(Object.hasOwn(p,k)&&(p[k]===null||typeof p[k]==='boolean'),'encounter_receipt_terminal_pause_observation_invalid');
  require(typeof result.input_release_confirmed==='boolean'&&typeof p.input_release_confirmed==='boolean'
    &&p.input_release_confirmed===result.input_release_confirmed,'encounter_receipt_terminal_pause_release_mismatch');
  if(p.outcome==='screen_installed')require(p.pause_call_attempted===true&&p.pause_screen_installed===true,'encounter_receipt_terminal_pause_installation_unproved');
  for(const k of ['error_type','reason'])if(Object.hasOwn(p,k))require(typeof p[k]==='string','encounter_receipt_terminal_pause_diagnostic_invalid');
}
export function validateEncounterReceipt(receipt, request) {
  const c=receipt?.result?.combat, e=c?.encounter;
  const expected=request?.encounter_mode===ENCOUNTER_MODE;
  if(!expected&&e===undefined)return;
  require(object(e)&&receipt.action_schema_version===1&&receipt.action==='combat_entity'&&receipt.ok===true&&receipt.server_confirmed===false,'encounter_receipt_missing');
  // This is the opt-in echo, never proof that a native pause has propagated.
  if(Object.hasOwn(e,'encounter_pause_on_terminal'))require(typeof e.encounter_pause_on_terminal==='boolean','encounter_receipt_pause_on_terminal_invalid');
  if(expected)require((e.encounter_pause_on_terminal===true)===(request.encounter_pause_on_terminal===true),'encounter_receipt_pause_on_terminal_mismatch');
  if(expected)require(receipt.result.world_generation===request.expected_world_generation&&receipt.action_session===request.expected_action_session,'encounter_receipt_context_mismatch');
  require(e.encounter_schema_version===1&&e.encounter_mode===ENCOUNTER_MODE,'encounter_receipt_schema_invalid');
  scope(e.encounter_scope);
  if(expected)require(e.encounter_scope.every((x,i)=>sameIdentity(x,request.encounter_scope[i])),'encounter_receipt_scope_mismatch');
  require(e.offense_disabled===true&&e.risk_remaining===true&&e.requires_handoff===true&&e.safety_assured===false,'encounter_receipt_risk_or_offense_invalid');
  require(c.attack_completed===false&&c.attack_dispatches===0&&c.target_dead_observed===false&&c.hits_confirmed===false&&c.server_confirmed===false&&c.safety_assured===false&&c.risk_remaining===true,'encounter_receipt_combat_claim_invalid');
  const target={entity_id:c.target_entity_id,uuid:c.target_uuid,type:c.target_type};identity(target);
  require(e.encounter_scope.some(x=>sameIdentity(x,target)),'encounter_receipt_target_mismatch');
  if(expected)require(c.target_entity_id===request.target_entity_id&&c.target_uuid===request.target_uuid&&c.target_type===request.target_type,'encounter_receipt_target_mismatch');
  require(integer(e.clearance_observations,0,3)&&e.danger_radius===8&&Object.hasOwn(e,'outcome_scope'),'encounter_receipt_observation_bounds_invalid');
  require(['running','succeeded','failed','cancelled'].includes(receipt.status),'encounter_receipt_status_invalid');
  if(receipt.status==='running'){require(e.outcome_scope===null,'encounter_receipt_premature_outcome');return;}
  if(e.encounter_pause_on_terminal===true)validateTerminalPause(receipt.result);
  require(e.terminal_status===receipt.status&&e.terminal_reason===receipt.reason&&typeof receipt.reason==='string'&&receipt.reason.length>0,'encounter_receipt_terminal_mismatch');
  if(receipt.status!=='succeeded'){require(e.outcome_scope===null,'encounter_receipt_failure_outcome_invalid');return;}
  require(receipt.reason==='encounter_clearance_observed'&&e.outcome_scope===OUTCOME&&e.clearance_observations===3&&receipt.result.input_release_confirmed===true,'encounter_receipt_success_not_proved');
  require(Array.isArray(e.scoped_living_threats)&&e.scoped_living_threats.length===2,'encounter_receipt_living_scope_missing');
  for(const [i,x] of e.scoped_living_threats.entries()){
    require(object(x)&&Object.keys(x).length===6&&[...identityKeys,'known','alive','clearance'].every(k=>Object.hasOwn(x,k)),'encounter_receipt_living_fields_invalid');
    const id=Object.fromEntries(identityKeys.map(k=>[k,x[k]]));identity(id);
    require(sameIdentity(id,e.encounter_scope[i])&&x.known===true&&x.alive===true&&typeof x.clearance==='number'&&Number.isFinite(x.clearance)&&x.clearance>8,'encounter_receipt_living_clearance_invalid');
  }
}
