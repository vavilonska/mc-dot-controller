/** Bounded action adapter only. No generic endpoint, credentials, retry, or plan execution. */
import {ENCOUNTER_MODE, encounterScopeSchema, encounterCondition, validateEncounterRequest, validateEncounterReceipt} from './encounter-contract.mjs';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const identity = ['expected_world_generation', 'expected_player_uuid', 'expected_action_session'];
const navigation = ['expected_navigation_epoch', 'expected_origin'];
const common = ['action_id', 'action', 'timeout_ms', ...identity];
const boatTransferFields = ['boat_transfer_schema_version', 'expected_game_time', 'vehicle_uuid', 'vehicle_entity_id', 'vehicle_type'];
const isBoatTransfer = action => action==='boat_mount'||action==='boat_dismount';
const timeoutBounds = action => isBoatTransfer(action)?[1000,5000]:action==='boat_drive'?[1000,120000]:action==='combat_entity'?[50,30000]:[50,600000];
const fields = {
  follow_path: [...navigation, 'waypoints', 'sprint', 'jump', 'sneak', 'hotbar_slot'],
  break_block: [...navigation, 'target', 'hotbar_slot', 'sneak'],
  place_block: [...navigation, 'support', 'face', 'hotbar_slot', 'jump', 'sneak'],
  click_slot: ['container_id', 'slot', 'button', 'click_type'],
  combat_entity: [...navigation, 'target_uuid', 'target_entity_id', 'target_type', 'approach', 'shield', 'hotbar_slot', 'encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal'],
  boat_drive: ['boat_schema_version', 'vehicle_uuid', 'vehicle_entity_id', 'vehicle_type', 'water_surface_y', 'waypoints'],
  boat_mount: boatTransferFields,
  boat_dismount: boatTransferFields
};
const point = {type: 'object', properties: {x:{type:'number'},y:{type:'number'},z:{type:'number'},jump:{type:'boolean'}}, required:['x','z'], additionalProperties:false};
const cell = {type:'object',properties:{x:{type:'integer'},y:{type:'integer'},z:{type:'integer'}},required:['x','y','z'],additionalProperties:false};
const properties = {
  action_id:{type:'string',pattern:ID.source,maxLength:128}, action:{type:'string',enum:Object.keys(fields)},
  timeout_ms:{type:'integer',minimum:50,maximum:600000},
  ...Object.fromEntries([...identity,'target_uuid','vehicle_uuid'].map(k=>[k,{type:'string',pattern:UUID.source}])),
  expected_navigation_epoch:{type:'integer',minimum:0,maximum:Number.MAX_SAFE_INTEGER},
  expected_origin:{type:'object',properties:{x:{type:'number'},y:{type:'number'},z:{type:'number'}},required:['x','y','z'],additionalProperties:false},
  waypoints:{type:'array',minItems:1,maxItems:512,items:point},target:cell,support:cell,
  face:{type:'string',enum:['up','down','north','south','east','west']},
  hotbar_slot:{type:'integer',minimum:0,maximum:8}, jump:{type:'boolean'},sneak:{type:'boolean'},sprint:{type:'boolean'},
  approach:{type:'boolean'},shield:{type:'boolean'},container_id:{type:'integer',minimum:0},slot:{type:'integer',minimum:-999},button:{type:'integer',minimum:0,maximum:40},
  click_type:{type:'string',enum:['pickup','quick_move','swap','throw','pickup_all','quick_craft']},
  target_entity_id:{type:'integer',minimum:0},target_type:{type:'string',enum:['minecraft:zombie','minecraft:husk','minecraft:zombie_villager','minecraft:skeleton','minecraft:stray','minecraft:bogged','minecraft:creeper']},
  encounter_mode:{type:'string',const:ENCOUNTER_MODE}, encounter_scope:encounterScopeSchema,
  encounter_pause_on_terminal:{type:'boolean',description:'Explicit two-zombie encounter opt-in only. Requests a native pause after terminal cleanup; no realtime or pause-effect guarantee.'},
  boat_transfer_schema_version:{type:'integer',const:1},expected_game_time:{type:'integer',minimum:0,maximum:Number.MAX_SAFE_INTEGER},
  boat_schema_version:{type:'integer',const:1},vehicle_entity_id:{type:'integer',minimum:0},vehicle_type:{type:'string',const:'minecraft:boat'},water_surface_y:{type:'integer',minimum:-2048,maximum:2048}
};
// Keep the top-level tool schema a plain object for strict MCP clients. Nested
// per-action variants describe the same required fields and principal bounds
// enforced below; no generic body or arbitrary endpoint is exposed.
const requiredByAction = {
  follow_path:['waypoints'], break_block:['target'], place_block:['support','face'],
  click_slot:['container_id','slot','button','click_type'],
  combat_entity:['target_uuid','target_entity_id','target_type'],
  boat_drive:['boat_schema_version','vehicle_uuid','vehicle_entity_id','vehicle_type','water_surface_y','waypoints'],
  boat_mount:boatTransferFields,
  boat_dismount:boatTransferFields
};
const variants = Object.entries(fields).map(([action,extra]) => {
  const p=Object.fromEntries([...common,...extra].map(k=>[k,properties[k]]));
  p.action={type:'string',const:action};
  const [minimum,maximum]=timeoutBounds(action);
  p.timeout_ms={type:'integer',minimum,maximum};
  if(isBoatTransfer(action)) {
    p.vehicle_entity_id={type:'integer',minimum:0,maximum:2147483647};
    for(const key of [...identity,'vehicle_uuid'])p[key]={type:'string',pattern:UUID.source,minLength:36,maxLength:36};
  }
  if(action==='follow_path') p.waypoints={type:'array',minItems:1,maxItems:512,items:{...point,required:['x','y','z']}};
  if(action==='boat_drive') p.waypoints={type:'array',minItems:1,maxItems:64,items:{type:'object',properties:{x:{type:'number'},z:{type:'number'}},required:['x','z'],additionalProperties:false}};
  return {type:'object',properties:p,required:[...common,...requiredByAction[action]],additionalProperties:false,...(action==='combat_entity'?{allOf:[encounterCondition]}:{})};
});
export const clientActionTool = {
  name:'minecraft_client_action',
  description:'Submit, inspect, or cancel one session-bound finite client action. Submit requires an explicit immutable action_id and expected world/player/action identities. One native owner; busy is rejected. Never retry an uncertain POST with a new ID. Inspect that original ID instead. This tool does not arbitrate external planners or take over an active resident/watchdog.',
  inputSchema:{type:'object',properties:{run_id:{type:'string'},operation:{type:'string',enum:['submit','status','cancel']},expected_action_session:{type:'string',pattern:UUID.source},action_id:{type:'string',pattern:ID.source,maxLength:128},body:{type:'object',properties,required:common,additionalProperties:false,oneOf:variants}},required:['run_id','operation','expected_action_session'],additionalProperties:false},
  annotations:{destructiveHint:true,openWorldHint:false}
};
function require(ok, reason) {if(!ok) throw new Error(reason);}
function object(x) {return x !== null && typeof x==='object' && !Array.isArray(x) && Object.getPrototypeOf(x)===Object.prototype;}
function exact(x, allowed, required=[]) {require(object(x),'action_object_required');require(Object.keys(x).every(k=>allowed.includes(k)),'action_unknown_field');require(required.every(k=>Object.hasOwn(x,k)),'action_required_field');}
function number(x, lo=-29999900, hi=29999900, integer=false) {require(typeof x==='number'&&Number.isFinite(x)&&x>=lo&&x<=hi&&(!integer||Number.isInteger(x)),'action_invalid_number');}
function uuid(x) {require(typeof x==='string'&&UUID.test(x),'action_invalid_uuid');}
function position(x, integer=false) {exact(x,['x','y','z'],['x','y','z']);for(const k of ['x','y','z'])number(x[k],-29999900,29999900,integer);}
export function parseClientAction(args, validateRunId = x => {require(typeof x==='string'&&ID.test(x),'invalid_run_id');return x;}) {
  exact(args,['run_id','operation','expected_action_session','action_id','body'],['run_id','operation','expected_action_session']);
  const runId=validateRunId(args.run_id);uuid(args.expected_action_session);
  require(['submit','status','cancel'].includes(args.operation),'action_invalid_operation');
  if(args.operation!=='submit') {
    require(!Object.hasOwn(args,'body')&&typeof args.action_id==='string'&&ID.test(args.action_id),'action_id_required_without_body');
    return {runId,actionId:args.action_id,operation:args.operation,session:args.expected_action_session,method:args.operation==='status'?'GET':'POST',endpoint:args.operation==='status'?'/control/action/status?action_id='+encodeURIComponent(args.action_id):'/control/action/cancel',body:args.operation==='cancel'?{action_id:args.action_id,expected_action_session:args.expected_action_session}:undefined};
  }
  require(!Object.hasOwn(args,'action_id'),'action_id_belongs_in_body');
  const b=args.body;require(object(b)&&Object.hasOwn(fields,b.action),'action_unsupported');
  exact(b,[...common,...fields[b.action]],isBoatTransfer(b.action)?[...common,...boatTransferFields]:common);
  require(Buffer.byteLength(JSON.stringify(b),'utf8')<=65536,'action_payload_too_large');
  require(typeof b.action_id==='string'&&ID.test(b.action_id),'action_invalid_id');
  for(const k of identity)uuid(b[k]);require(b.expected_action_session===args.expected_action_session,'action_session_mismatch');
  const [minimum,maximum]=timeoutBounds(b.action);
  number(b.timeout_ms,minimum,maximum,true);
  for(const k of ['jump','sneak','sprint','approach','shield','encounter_pause_on_terminal'])if(Object.hasOwn(b,k))require(typeof b[k]==='boolean','action_invalid_boolean');
  if(Object.hasOwn(b,'hotbar_slot'))number(b.hotbar_slot,0,8,true);
  require(Object.hasOwn(b,'expected_navigation_epoch')===Object.hasOwn(b,'expected_origin'),'action_navigation_binding_pair_required');
  if(Object.hasOwn(b,'expected_navigation_epoch')) {number(b.expected_navigation_epoch,0,Number.MAX_SAFE_INTEGER,true);position(b.expected_origin);}
  if(b.action==='follow_path'||b.action==='boat_drive') {
    require(Array.isArray(b.waypoints)&&b.waypoints.length>0&&b.waypoints.length<=(b.action==='boat_drive'?64:512),'action_invalid_waypoints');
    for(const p of b.waypoints) {
      const keys=b.action==='boat_drive'?['x','z']:['x','y','z','jump'];exact(p,keys,b.action==='boat_drive'?keys:['x','y','z']);
      for(const k of keys.filter(k=>k!=='jump'))number(p[k]);if(Object.hasOwn(p,'jump'))require(typeof p.jump==='boolean','action_invalid_jump');
    }
  }
  if(b.action==='break_block')position(b.target,true);
  if(b.action==='place_block') {position(b.support,true);require(properties.face.enum.includes(b.face),'action_invalid_face');}
  if(b.action==='combat_entity') {uuid(b.target_uuid);number(b.target_entity_id,0,2147483647,true);require(properties.target_type.enum.includes(b.target_type),'action_unsupported_target');}
  validateEncounterRequest(b);
  if(isBoatTransfer(b.action)) {
    require(b.boat_transfer_schema_version===1&&b.vehicle_type==='minecraft:boat','action_invalid_boat_transfer_schema');
    for(const key of [...identity,'vehicle_uuid']) {uuid(b[key]);require(b[key].length===36,'action_invalid_uuid');}
    number(b.vehicle_entity_id,0,2147483647,true);number(b.expected_game_time,0,Number.MAX_SAFE_INTEGER,true);
  }
  if(b.action==='boat_drive') {
    require(b.boat_schema_version===1&&b.vehicle_type==='minecraft:boat','action_invalid_boat_schema');uuid(b.vehicle_uuid);number(b.vehicle_entity_id,0,2147483647,true);number(b.water_surface_y,-2048,2048,true);
    let length=0;for(let i=1;i<b.waypoints.length;i++){const d=Math.hypot(b.waypoints[i].x-b.waypoints[i-1].x,b.waypoints[i].z-b.waypoints[i-1].z);require(d>=.25&&d<=16,'action_invalid_boat_segment');length+=d;}require(length<=256,'action_boat_route_too_long');
  }
  if(b.action==='click_slot') {
    number(b.container_id,0,2147483647,true);number(b.slot,-999,2147483647,true);require(b.slot>=0||b.slot===-999,'action_invalid_slot');number(b.button,0,40,true);require(properties.click_type.enum.includes(b.click_type),'action_invalid_click');
    require(b.click_type==='swap'?(b.button<=8||b.button===40):b.click_type==='quick_craft'?(b.button<=10&&(b.button&3)<=2):b.button<=1,'action_invalid_button');
  }
  return {runId,actionId:b.action_id,operation:'submit',session:args.expected_action_session,method:'POST',endpoint:'/control/action',body:structuredClone(b)};
}
export async function executeClientAction(args, hooks) {
  const p=parseClientAction(args,hooks.validateRunId);
  const descriptor=await hooks.readDescriptor(p.runId);
  const status=await hooks.revalidateSession(descriptor);
  require(status?.client_action?.action_session===p.session,'action_session_changed');
  if(p.operation==='submit') {
    require(status?.world?.world_generation===p.body.expected_world_generation,'action_world_changed');
    require(status?.player?.uuid===p.body.expected_player_uuid,'action_player_changed');
    hooks.assertInputIsolation(descriptor,status);
  }
  // Exactly one request. A failure may mean the POST already executed: no retry,
  // no new action ID, no release-all, and no automatic cancellation side effect.
  let result;
  try {
    result=await hooks.requestJson(descriptor,p.method,p.endpoint,p.body);
    require(result?.action_session===p.session,'action_response_session_changed');
    require(result?.action_id===p.actionId,'action_response_id_changed');
    require(result?.ok===true && result?.action_schema_version===1 && ['running','succeeded','failed','cancelled'].includes(result?.status),'action_response_invalid');
    if(p.operation==='submit') require(result?.action===p.body.action,'action_response_type_changed');
    validateEncounterReceipt(result,p.operation==='submit'?p.body:undefined);
  } catch (error) {
    // A malformed or mismatched response is just as uncertain as a network loss:
    // the original POST may already have changed client state.
    if(p.method==='POST') throw new Error('action_request_failed_outcome_unknown; inspect the original action_id in the same action session; do not replay or allocate a new ID', {cause:error});
    throw error;
  }
  return {run_id:descriptor.run_id,process_id:descriptor.process_id,operation:p.operation,bridge:hooks.sanitizeForOutput(result,descriptor.token)};
}
