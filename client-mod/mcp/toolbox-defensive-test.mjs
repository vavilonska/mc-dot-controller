import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {executeToolbox} from './toolbox.mjs';
for(const lost of [false,true])test(`defensive public chain ${lost?'unknown retained':'bounded completion and release'}`,{timeout:15000},async()=>{
 const child=spawn(process.env.PYTHON||'python3',['-B',fileURLToPath(new URL('./toolbox-defensive-fixture.py',import.meta.url))],{stdio:['pipe','pipe','pipe']});
 let stderr='',counter=0,closed=false;child.stderr.setEncoding('utf8');child.stderr.on('data',s=>stderr+=s);
 const queue=[],waiters=[],lines=createInterface({input:child.stdout});
 lines.on('line',line=>{const v=JSON.parse(line),w=waiters.shift();if(w)w.resolve(v);else queue.push(v);});
 const exit=new Promise((resolve,reject)=>{child.on('error',reject);child.on('close',(code,signal)=>{closed=true;for(const w of waiters.splice(0))w.reject(Error(stderr));resolve({code,signal});});});
 const next=()=>queue.length?Promise.resolve(queue.shift()):closed?Promise.reject(Error(stderr)):new Promise((resolve,reject)=>waiters.push({resolve,reject}));
 const request=async b=>{const id=++counter;child.stdin.write(JSON.stringify({id,...b})+'\n');const v=await next();assert.equal(v.id,id);return v.result;};
 try{
  const ready=await next();assert.equal(ready.ready,true);const backend={call:(name,args)=>request({name,arguments:args})};
  const cat=await executeToolbox('mdc_catalog',{api_version:'mdc.toolbox/1',capability_ids:['defend_local']},{backend});assert.equal(cat.capabilities[0].runtime_available,true);
  if(lost)await request({command:'lose'});
  const args={api_version:'mdc.toolbox/1',operation:'submit',request_id:'node-defend-once',session_ref:ready.session_ref,expected_context_ref:ready.context_ref,capability:'defend_local',capability_version:1,arguments:{target_uuid:'44444444-4444-4444-8444-444444444444',window_ms:1000},policy:{version:1,execution_mode:'guarded',reactions:'stop'},budgets:{max_actions:3,max_observations:32,deadline_seconds:10},wait_ms:0};
  const result=await executeToolbox('mdc_job',args,{backend});assert.equal(result.state,lost?'unknown':'succeeded',JSON.stringify(result));assert.ok(result.job_id);assert.ok(result.request_ids.length>=2);
  const again=await executeToolbox('mdc_job',args,{backend});assert.equal(again.job_id,result.job_id);assert.equal(again.state,result.state);
  const proof=await request({command:'proof'});const posts=proof.calls.filter(x=>x[0]==='/control/scoped-action');assert.equal(posts.length,1);
  assert.equal(posts[0][1].preflight.profile,'combat-defensive-local-v1');assert.equal(posts[0][1].preflight.job_id,result.job_id);
  assert.equal(posts[0][1].intent.defensive_policy.mode,'shield_only');assert.equal(posts[0][1].intent.approach,false);
  assert.equal(proof.calls.filter(x=>x[0]==='/control/action').length,0);
  if(lost){assert.ok(proof.lease);}else{assert.equal(proof.lease,null);assert.equal(result.cleanup_certainty,'confirmed');}
 }finally{child.stdin.end();assert.deepEqual(await exit,{code:0,signal:null},stderr);lines.close();}
});
