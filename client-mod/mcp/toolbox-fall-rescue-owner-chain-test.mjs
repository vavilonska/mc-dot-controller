/** Production JS facade -> Python owner -> watchdog -> resident; synthetic native endpoint. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {executeToolbox} from './toolbox.mjs';

test('public fall guard uses the existing sole owner and exact cancel', {timeout:15000}, async()=>{
 const fixture=fileURLToPath(new URL('./toolbox-fall-rescue-owner-chain-fixture.py',import.meta.url));
 const child=spawn(process.env.PYTHON||'python3',['-B',fixture],{stdio:['pipe','pipe','pipe']});
 let stderr='',counter=0,ended=false;child.stderr.setEncoding('utf8');child.stderr.on('data',s=>stderr+=s);
 const queue=[],waiters=[],lines=createInterface({input:child.stdout});
 lines.on('line',line=>{const value=JSON.parse(line),w=waiters.shift();if(w)w.resolve(value);else queue.push(value);});
 child.on('exit',()=>{ended=true;for(const w of waiters.splice(0))w.reject(Error(stderr));});
 const next=()=>queue.length?Promise.resolve(queue.shift()):ended?Promise.reject(Error(stderr)):new Promise((resolve,reject)=>waiters.push({resolve,reject}));
 const request=async body=>{const id=++counter;child.stdin.write(JSON.stringify({id,...body})+'\n');const r=await next();assert.equal(r.id,id);return r.result;};
 const exit=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
 try{
  const ready=await next();assert.equal(ready.ready,true);assert.equal(ready.synthetic_native,true);
  const backend={call:(name,args)=>request({name,arguments:args})};
  const catalog=await executeToolbox('mdc_catalog',{api_version:'mdc.toolbox/1',capability_ids:['fall_rescue_guard'],detail:'contracts'},{backend});
  assert.equal(catalog.capabilities[0].runtime_available,true);assert.equal(catalog.capabilities[0].resume_supported,false);
  const submit={api_version:'mdc.toolbox/1',operation:'submit',request_id:'node-fall-once',session_ref:ready.session_ref,expected_context_ref:ready.context_ref,
    capability:'fall_rescue_guard',capability_version:1,arguments:{duration_ms:4000},policy:{version:1,execution_mode:'request_only',reactions:'stop'},
    budgets:{deadline_seconds:20,max_actions:16,max_observations:64},wait_ms:0};
  const submitted=await executeToolbox('mdc_job',submit,{backend});assert.equal(submitted.state,'running',JSON.stringify(submitted));
  const cancel={api_version:'mdc.toolbox/1',operation:'cancel',job_id:submitted.job_id,session_ref:ready.session_ref,cancel_request_id:'node-stop-fall',wait_ms:0};
  const terminal=await executeToolbox('mdc_job',cancel,{backend});assert.equal(terminal.state,'cancelled',JSON.stringify(terminal));assert.equal(terminal.cleanup_certainty,'confirmed');
  const proof=await request({command:'proof'});assert.equal(proof.capability_lease,null);
  const writes=proof.fall_calls.filter(([op])=>op!=='status');assert.deepEqual(writes.map(([op])=>op),['arm','disarm']);
  assert.equal(writes[0][1].arm_id,writes[1][1].arm_id);assert.equal(writes[0][1].owner_id,writes[1][1].owner_id);
  assert.deepEqual(writes[0][1].permitted_action_ids,[]);assert.deepEqual(proof.calls[1],{name:'mdc_job',arguments:submit});
 }finally{child.stdin.end();assert.deepEqual(await exit,{code:0,signal:null},stderr);lines.close();}
});
