import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import {toolboxSchemas,executeToolbox} from './toolbox.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
const python=process.env.PYTHON || 'python3';
// T20 request shape and limits; opaque live IDs replaced for portable publication.
export const request={api_version:'mdc.toolbox/1',operation:'submit',request_id:'toolbox-t20-engage-once',session_ref:'synthetic-session',expected_context_ref:'synthetic-context',capability:'engage',capability_version:1,arguments:{approach:false,min_health:18,shield:true,target_uuid:'44444444-4444-4444-8444-444444444444',timeout_ms:4000},budgets:{cleanup_reserve_actions:1,deadline_seconds:10,max_actions:3,max_observations:24,reflex_reserve_actions:0},policy:{execution_mode:'request_only',reactions:'stop',version:1},wait_ms:0};
const plan=()=>Object.fromEntries(Object.entries(request).filter(([k])=>['api_version','capability','capability_version','arguments','policy','budgets','session_ref'].includes(k)));
test('entire embedded schemas equal pure Python contracts and check mode is clean',()=>{
 const code="import importlib.util,json,sys; s=importlib.util.spec_from_file_location('contracts',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.TOOL_SCHEMAS)); assert not any(k.startswith(('mdc_skills','resident_controller','mdc_toolbox')) for k in sys.modules)";
 const r=spawnSync(python,['-B','-c',code,path.resolve(here,'../../capability-runtime/mdc_toolbox/contracts.py')],{encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);assert.deepEqual(toolboxSchemas,JSON.parse(r.stdout));
 const check=spawnSync(python,['-B',path.join(here,'sync-toolbox-schema.py'),'--check'],{encoding:'utf8'});assert.equal(check.status,0,check.stderr);
});
test('all three policy locations advertise exactly the canonical modes',()=>{
 const schemas=[toolboxSchemas.mdc_plan,toolboxSchemas.mdc_job,toolboxSchemas.mdc_job.allOf[0].then];
 for(const schema of schemas)assert.deepEqual(schema.properties.policy.properties.execution_mode.enum,['noncombat','guarded','request_only']);
});
test('production wrapper forwards request_only job and plan unchanged once',async()=>{
 for(const [name,args] of [['mdc_job',request],['mdc_plan',plan()]]){
  let calls=0;const before=JSON.stringify(args);const result=await executeToolbox(name,args,{backend:{call(n,a){calls++;assert.equal(n,name);assert.deepEqual(a,args);return {forwarded:true};}}});
  assert.equal(calls,1);assert.deepEqual(result,{forwarded:true});assert.equal(JSON.stringify(args),before);
 }
});
test('unknown policy still refuses before backend and standard/noncombat remain valid',async()=>{
 for(const mode of ['standard','request_only_typo','',null]){let calls=0;const r=await executeToolbox('mdc_job',{...request,policy:{...request.policy,execution_mode:mode}},{backend:{call(){calls++;}}});assert.equal(r.error.code,'invalid_request');assert.equal(calls,0);}
 for(const mode of ['noncombat','guarded']){let calls=0;await executeToolbox('mdc_job',{...request,policy:{...request.policy,execution_mode:mode}},{backend:{call(){calls++;return {};}}});assert.equal(calls,1);}
});
test('real production NDJSON MCP front door accepts job/plan policy without a configured runtime',()=>{
 const env={...process.env};delete env.MINECLIENT_TOOLBOX_CONFIG;
 const requests=[{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'mdc_job',arguments:request}},{jsonrpc:'2.0',id:2,method:'tools/call',params:{name:'mdc_plan',arguments:plan()}}];
 const run=spawnSync(process.execPath,[path.join(here,'mineclient-bridge-mcp.mjs')],{env,input:requests.map(x=>JSON.stringify(x)).join('\n')+'\n',encoding:'utf8',timeout:10000});
 assert.equal(run.status,0,run.stderr);const replies=run.stdout.trim().split('\n').map(JSON.parse);assert.equal(replies.length,2);
 for(const reply of replies){const body=JSON.parse(reply.result.content[0].text);assert.equal(body.error.code,'capability_unavailable');assert.equal(body.error.effect_certainty,'none_proven');}
});

test('check mode detects drift without modifying files and regeneration is deterministic',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mdc-schema-parity-'));
 try {
  const mc=path.join(root,'client-mod/mcp'),py=path.join(root,'capability-runtime/mdc_toolbox');fs.mkdirSync(mc,{recursive:true});fs.mkdirSync(py,{recursive:true});
  for(const name of ['sync-toolbox-schema.py','toolbox.mjs'])fs.copyFileSync(path.join(here,name),path.join(mc,name));
  fs.copyFileSync(path.resolve(here,'../../capability-runtime/mdc_toolbox/contracts.py'),path.join(py,'contracts.py'));
  const target=path.join(mc,'toolbox.mjs'),original=fs.readFileSync(target,'utf8'),drift=original.replaceAll(',"request_only"','');fs.writeFileSync(target,drift);
  const check=spawnSync(python,[path.join(mc,'sync-toolbox-schema.py'),'--check'],{encoding:'utf8'});assert.equal(check.status,1);assert.equal(fs.readFileSync(target,'utf8'),drift);assert.deepEqual(fs.readdirSync(py),['contracts.py']);
  const fix=spawnSync(python,['-B',path.join(mc,'sync-toolbox-schema.py')],{encoding:'utf8'});assert.equal(fix.status,0,fix.stderr);assert.equal(fs.readFileSync(target,'utf8'),original);
 } finally {fs.rmSync(root,{recursive:true,force:true});}
});
