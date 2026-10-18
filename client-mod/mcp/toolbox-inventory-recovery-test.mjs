/** Production JS -> Python public service/owner chain. Native inventory is synthetic. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {executeToolbox} from './toolbox.mjs';
test('public recovery contracts, exact cursor and immutable dedup cross the actual owner chain', {timeout:20000},async()=>{
 const child=spawn(process.env.PYTHON||'python3',['-B',fileURLToPath(new URL('./toolbox-inventory-recovery-fixture.py',import.meta.url))],{stdio:['pipe','pipe','pipe']});
 let stderr='',serial=0,ended=false;child.stderr.setEncoding('utf8');child.stderr.on('data',s=>stderr+=s);
 const queue=[],waiters=[];const lines=createInterface({input:child.stdout});
 lines.on('line',line=>{const v=JSON.parse(line),waiter=waiters.shift();if(waiter)waiter.resolve(v);else queue.push(v);});
 child.on('exit',()=>{ended=true;for(const waiter of waiters.splice(0))waiter.reject(new Error(stderr));});
 const next=()=>queue.length?Promise.resolve(queue.shift()):ended?Promise.reject(new Error(stderr)):new Promise((resolve,reject)=>waiters.push({resolve,reject}));
 const request=async body=>{const id=++serial;child.stdin.write(JSON.stringify({id,...body})+'\n');const answer=await next();assert.equal(answer.id,id);return answer.result;};
 const exit=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
 try {
  const ready=await next();assert.equal(ready.ready,true);assert.equal(ready.synthetic_native,true);
  const backend={call(name,args){return request({name,arguments:args});}};
  const api_version='mdc.toolbox/1';
  const catalog=await executeToolbox('mdc_catalog',{api_version,capability_ids:['clear_hand','recover_cursor'],detail:'contracts'},{backend});
  assert.equal(catalog.capabilities.length,2);assert(catalog.capabilities.every(c=>c.runtime_available&&c.native_features.includes('inventory-recovery/1')));
  assert(catalog.capabilities.every(c=>c.requirements.explicit_request_required&&!c.normal_fallback.automatic));
  const submit=(capability,args,request_id)=>({api_version,operation:'submit',session_ref:ready.session_ref,expected_context_ref:ready.context_ref,
    capability,capability_version:1,arguments:args,request_id,policy:{version:1,execution_mode:'guarded',reactions:'stop'},
    budgets:{max_actions:7,max_observations:64,deadline_seconds:30},wait_ms:0});
  const malformed=await executeToolbox('mdc_job',submit('recover_cursor',{},'missing-binding'),{backend});assert.equal(malformed.error.code,'invalid_request');
  const stale=await executeToolbox('mdc_job',submit('recover_cursor',{...ready.cursor_arguments,cursor_fingerprint:'changed'},'changed-cursor'),{backend});assert.equal(stale.state,'blocked');
  const recover=submit('recover_cursor',ready.cursor_arguments,'recover-exact');const copied=JSON.stringify(recover);
  const recovered=await executeToolbox('mdc_job',recover,{backend});assert.equal(recovered.state,'succeeded',JSON.stringify(recovered));assert.equal(recovered.cleanup_certainty,'confirmed');assert.equal(JSON.stringify(recover),copied);
  const clear=submit('clear_hand',{hand:'both'},'clear-exact');
  const result=await executeToolbox('mdc_job',clear,{backend});assert.equal(result.state,'succeeded',JSON.stringify(result));assert.equal(result.effect_certainty,'known');assert.equal(result.cleanup_certainty,'confirmed');
  const duplicate=await executeToolbox('mdc_job',clear,{backend});assert.equal(duplicate.job_id,result.job_id);
  const proof=await request({command:'proof'});assert.equal(proof.lease,null);assert.equal(proof.commands.length,5);
  assert.equal(proof.inventory.inventory[0].empty,true);assert.equal(proof.inventory.offhand.empty,true);assert.equal(proof.menu.carried.empty,true);
  assert.equal(proof.posts.filter(([path])=>path==='/control/action').length,0);
  assert.equal(proof.posts.filter(([path])=>path==='/control/scoped-action').length,5);
 } finally {child.stdin.end();const result=await exit;lines.close();assert.deepEqual(result,{code:0,signal:null},stderr);}
});
