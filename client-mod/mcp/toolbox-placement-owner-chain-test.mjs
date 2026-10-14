/** Real JS validation + Python owner/mailbox chain; all native effects are synthetic. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {executeToolbox} from './toolbox.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
async function fixture(mode,body){
 const child=spawn(process.env.PYTHON||'python3',['-B',path.join(here,'toolbox-placement-owner-chain-fixture.py'),mode],{stdio:['pipe','pipe','pipe']});
 let stderr='',counter=0,ended=false;child.stderr.setEncoding('utf8');child.stderr.on('data',s=>stderr+=s);
 const waiters=[],buffer=[];const lines=createInterface({input:child.stdout});
 lines.on('line',line=>{const value=JSON.parse(line),waiter=waiters.shift();if(waiter)waiter.resolve(value);else buffer.push(value);});
 child.on('exit',()=>{ended=true;for(const waiter of waiters.splice(0))waiter.reject(new Error(stderr||'fixture exited'));});
 const next=()=>buffer.length?Promise.resolve(buffer.shift()):ended?Promise.reject(new Error(stderr||'fixture exited')):new Promise((resolve,reject)=>waiters.push({resolve,reject}));
 const request=async command=>{const id=++counter;child.stdin.write(JSON.stringify({id,...command})+'\n');const response=await next();assert.equal(response.id,id);return response.result;};
 const exit=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
 try{const ready=await next();assert.equal(ready.ready,true);assert.equal(ready.execution_policy,'request_only');await body(ready,request);}
 finally{child.stdin.end();const closed=await exit;lines.close();assert.deepEqual(closed,{code:0,signal:null},stderr);}
}
function submit(ready,mode){return {api_version:'mdc.toolbox/1',operation:'submit',request_id:'offline-place-'+mode,session_ref:ready.session_ref,expected_context_ref:ready.context_ref,
 capability:'place_local',capability_version:1,arguments:ready.arguments,policy:{version:1,execution_mode:'request_only',reactions:'stop'},
 budgets:{max_actions:3,max_observations:24,deadline_seconds:10,cleanup_reserve_actions:1,reflex_reserve_actions:0},wait_ms:0};}
for(const mode of ['success','cancel','lost','late409','effect_unknown','profile_missing','no_decrement','invalid_arguments']){
 test('placement production wrapper to Python owner-chain: '+mode,{timeout:20000},async()=>fixture(mode,async(ready,request)=>{
  const args=submit(ready,mode);if(mode==='invalid_arguments')args.arguments={...args.arguments,face:'diagonal'};
  const original=structuredClone(args),forwarded=[];
  const backend={call(name,arguments_){forwarded.push({name,arguments:structuredClone(arguments_)});return request({name,arguments:arguments_});}};
  let result=await executeToolbox('mdc_job',args,{backend});assert.deepEqual(args,original);assert.equal(forwarded.length,1);
  if(mode==='cancel'){
   assert.equal(result.state,'running',JSON.stringify(result));
   result=await executeToolbox('mdc_job',{api_version:'mdc.toolbox/1',operation:'cancel',session_ref:ready.session_ref,job_id:result.job_id,cancel_request_id:'offline-place-cancel-once',wait_ms:1000},{backend});
  }
  const proof=await request({command:'proof'});assert.deepEqual(proof.calls,forwarded);assert.equal(proof.legacy_posts.length,0);
  if(mode==='profile_missing'||mode==='invalid_arguments'){
   assert.ok(result.error||result.state==='blocked',JSON.stringify(result));assert.equal(proof.scoped_posts.length,0);assert.equal(proof.decrements,0);return;
  }
  assert.equal(proof.scoped_posts.length,1);assert.equal(proof.fixture_error,null);
  const dispatch=proof.scoped_posts[0];assert.equal(dispatch.preflight.profile,'placement-local-observed-v1');
  assert.equal(dispatch.intent.action,'place_block');assert.equal(dispatch.intent.placement_footprint.length,1);
  assert.deepEqual(dispatch.intent.support,ready.arguments.support);assert.equal(dispatch.intent.face,ready.arguments.face);
  assert.deepEqual(dispatch.intent.placement_hit,{x:2.5,y:64,z:.5});
  if(mode==='success'){
   assert.equal(result.state,'succeeded',JSON.stringify(result));assert.equal(result.effect_certainty,'known');assert.equal(result.cleanup_certainty,'confirmed');
   assert.equal(proof.placed,true);assert.equal(proof.decrements,1);assert.equal(proof.final_count,proof.initial_count-1);assert.equal(proof.cancel_posts.length,0);assert.equal(proof.capability_lease,null);
  }else if(mode==='cancel'){
   assert.equal(result.state,'cancelled',JSON.stringify(result));assert.equal(result.cleanup_certainty,'confirmed');assert.equal(proof.placed,false);assert.equal(proof.decrements,0);
   assert.equal(proof.cancel_posts.length,1);assert.equal(proof.cancel_posts[0].action_id,dispatch.intent.action_id);assert.equal(proof.capability_lease,null);
  }else if(mode==='lost'||mode==='late409'||mode==='effect_unknown'){
   assert.equal(result.state,'unknown',JSON.stringify(result));assert.equal(result.effect_certainty,'unknown');assert.equal(proof.decrements,mode==='lost'?0:1);assert.equal(proof.cancel_posts.length,0);
  }else{
   assert.notEqual(result.state,'succeeded');assert.equal(proof.placed,true);assert.equal(proof.decrements,0);assert.equal(proof.final_count,proof.initial_count);
  }
 }));
}
test('placement invalid public schema never reaches Python backend',async()=>{
 let calls=0;
 const r=await executeToolbox('mdc_job',{api_version:'mdc.toolbox/1',operation:'submit',session_ref:'s',expected_context_ref:'c',request_id:'bad-schema',
  capability:'place_local',capability_version:1,arguments:{},policy:{version:1,execution_mode:'request_only_typo'},budgets:{max_actions:3,deadline_seconds:10}},{backend:{call(){calls++;}}});
 assert.equal(r.error.code,'invalid_request');assert.equal(calls,0);
});
