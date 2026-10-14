/** Actual JS validation -> Python subprocess -> Owner/Resident; native is synthetic. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {executeToolbox} from './toolbox.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));

test('production executeToolbox forwards unchanged into real Python owner/Resident subprocess', {timeout:15000}, async()=>{
 const child=spawn(process.env.PYTHON||'python3',['-B',path.join(here,'toolbox-owner-chain-fixture.py')],{stdio:['pipe','pipe','pipe']});
 let stderr='',counter=0;child.stderr.setEncoding('utf8');child.stderr.on('data',s=>{stderr+=s;});
 const readers=[],buffer=[];
 const lines=createInterface({input:child.stdout});
 lines.on('line',line=>{const value=JSON.parse(line);const waiter=readers.shift();if(waiter)waiter.resolve(value);else buffer.push(value);});
 let ended=false;
 child.on('exit',()=>{ended=true;for(const waiter of readers.splice(0))waiter.reject(new Error('Python fixture exited: '+stderr));});
 const next=()=>buffer.length?Promise.resolve(buffer.shift()):ended?Promise.reject(new Error('Python fixture exited: '+stderr)):new Promise((resolve,reject)=>readers.push({resolve,reject}));
 const request=async body=>{const id=++counter;child.stdin.write(JSON.stringify({id,...body})+'\n');const response=await next();assert.equal(response.id,id);return response.result;};
 const exit=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
 try {
  const ready=await next();assert.equal(ready.ready,true);assert.equal(ready.execution_policy,'request_only');assert.equal(ready.synthetic_native,true);
  const submit={api_version:'mdc.toolbox/1',operation:'submit',request_id:'offline-mcp-request-only-once',session_ref:ready.session_ref,expected_context_ref:ready.context_ref,
   capability:'engage',capability_version:1,arguments:{target_uuid:ready.target_uuid,approach:false,shield:true,min_health:18,timeout_ms:4000},
   policy:{version:1,execution_mode:'request_only',reactions:'stop'},budgets:{max_actions:3,max_observations:24,deadline_seconds:10,cleanup_reserve_actions:1,reflex_reserve_actions:0},wait_ms:0};
  const before=JSON.stringify(submit);let forwarded=0;
  const backend={call(name,args){forwarded++;return request({name,arguments:args});}};
  const running=await executeToolbox('mdc_job',submit,{backend});
  assert.equal(running.state,'running',JSON.stringify(running));assert.equal(JSON.stringify(submit),before);
  const cancel={api_version:'mdc.toolbox/1',operation:'cancel',job_id:running.job_id,session_ref:ready.session_ref,cancel_request_id:'offline-mcp-cancel-once',wait_ms:1000};
  const terminal=await executeToolbox('mdc_job',cancel,{backend});
  assert.equal(terminal.state,'cancelled',JSON.stringify(terminal));assert.equal(terminal.effect_certainty,'known');assert.equal(terminal.cleanup_certainty,'confirmed');assert.equal(terminal.continuation,'none');
  const proof=await request({command:'proof'});
  assert.equal(forwarded,2);assert.deepEqual(proof.calls,[{name:'mdc_job',arguments:submit},{name:'mdc_job',arguments:cancel}]);
  assert.equal(proof.scoped_posts.length,1);assert.equal(proof.cancel_posts.length,1);assert.equal(proof.legacy_posts.length,0);
  assert.equal(proof.scoped_posts[0].preflight.profile,'combat-local-observed-v1');
  assert.equal(proof.scoped_posts[0].intent.target_uuid,ready.target_uuid);
  assert.equal(proof.cancel_posts[0].action_id,proof.scoped_posts[0].intent.action_id);
  assert.equal(proof.capability_lease,null);assert.equal(proof.execution_policy,'request_only');
 } finally {
  // Ordinary EOF teardown only: no forced signals, native transport or action replay.
  child.stdin.end();const result=await exit;lines.close();assert.deepEqual(result,{code:0,signal:null},stderr);
 }
});
