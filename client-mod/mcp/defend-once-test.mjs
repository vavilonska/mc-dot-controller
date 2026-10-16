import test from 'node:test';
import assert from 'node:assert/strict';
import {executeToolbox} from './toolbox.mjs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const request={api_version:'mdc.toolbox/1',operation:'submit',request_id:'defend-once-mcp',session_ref:'synthetic-session',expected_context_ref:'synthetic-context',capability:'navigate_local',capability_version:1,arguments:{goal:{x:1,y:64,z:0}},policy:{version:1,execution_mode:'request_only',reactions:'defend_once',defense:{target_uuid:'44444444-4444-4444-8444-444444444444',timeout_ms:2000,min_health:14}},budgets:{deadline_seconds:30,max_actions:3,max_observations:20,reflex_reserve_actions:1,cleanup_reserve_actions:1},wait_ms:0};
test('explicit defend_once forwards unchanged exactly once',async()=>{
 let calls=0;const result=await executeToolbox('mdc_job',request,{backend:{call(name,args){calls++;assert.deepEqual(args,request);return {accepted:true};}}});
 assert.deepEqual(result,{accepted:true});assert.equal(calls,1);
});
test('defense shape and mode are closed before forwarding',async()=>{
 for(const change of [p=>delete p.defense,p=>delete p.defense.target_uuid,p=>p.defense.timeout_ms=5001,p=>p.defense.min_health=13,p=>p.execution_mode='noncombat',p=>p.reactions='stop',p=>p.defense.target_uuid='arbitrary']){
  const args=structuredClone(request);change(args.policy);let calls=0;
  const result=await executeToolbox('mdc_job',args,{backend:{call(){calls++;return {};}}});
  assert.equal(result.error.code,'invalid_request');assert.equal(calls,0);
 }
});
test('production NDJSON MCP admits schema then correctly requires configured runtime',()=>{
 const env={...process.env};delete env.MINECLIENT_TOOLBOX_CONFIG;
 const run=spawnSync(process.execPath,[fileURLToPath(new URL('./mineclient-bridge-mcp.mjs',import.meta.url))],{env,input:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'mdc_job',arguments:request}})+'\n',encoding:'utf8',timeout:10000});
 assert.equal(run.status,0,run.stderr);const response=JSON.parse(run.stdout.trim());
 assert.equal(JSON.parse(response.result.content[0].text).error.code,'capability_unavailable');
});
