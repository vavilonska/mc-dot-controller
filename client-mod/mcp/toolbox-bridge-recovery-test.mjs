/** Actual ToolboxBridge, synthetic child event ordering; no process or game. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough, Writable} from 'node:stream';
import {ToolboxBridge} from './toolbox-bridge.mjs';

function fixture(options={}) {
  const child=new EventEmitter();
  child.stdout=new PassThrough();child.stderr=new PassThrough();child.writes=[];
  child.stdin=new Writable({write(chunk,_encoding,done){child.writes.push(Buffer.from(chunk));done();}});
  const bridge=new ToolboxBridge(child,{requestTimeoutMs:1000,drainTimeoutMs:50,...options});
  return {child,bridge};
}
const request={api_version:'mdc.toolbox/1',operation:'status',session_ref:'original_session',job_id:'original_job'};
function finish(child,code=0){child.stdout.end();child.stderr.end();child.emit('close',code,null);}


test('exit before final stdout does not discard complete terminal job proof',async()=>{
  const {child,bridge}=fixture();
  const pending=bridge.call('mdc_job',request);
  const result={api_version:'mdc.toolbox/1',job_id:'original_job',request_id:'original_request',
    request_ids:['native_original'],state:'succeeded',effect_certainty:'known',cleanup_certainty:'confirmed',error:null};
  child.emit('exit',0,null);
  assert.equal(bridge.terminal,false);
  child.stdout.write(JSON.stringify({id:'tb_1',result})+'\n');
  finish(child);
  assert.deepEqual(await pending,result);
  assert.deepEqual(await bridge.close(),{exit_code:0,reason:'service_exited'});
  assert.equal(child.writes.length,1);
});

test('split final frame drains after exit and keeps failure job_id',async()=>{
  const {child,bridge}=fixture();
  const pending=bridge.call('mdc_job',request);
  const result={job_id:'original_job',request_id:'original_request',request_ids:['native_original'],state:'unknown',
    effect_certainty:'known',cleanup_certainty:'unknown',error:{code:'outcome_unknown',reason:'release not confirmed'}};
  const frame=JSON.stringify({id:'tb_1',result})+'\n';
  child.stdout.write(frame.slice(0,43));child.emit('exit',3,null);
  child.stdout.write(frame.slice(43));finish(child,3);
  assert.deepEqual(await pending,result);
  assert.equal(child.writes.length,1);
});

test('bounded missing-close drain remains unknown with original identity and no replay',async()=>{
  const {child,bridge}=fixture({drainTimeoutMs:10});
  const pending=bridge.call('mdc_job',request);
  child.emit('exit',3,null);
  const result=await pending;
  assert.equal(result.state,'unknown');assert.equal(result.cleanup_certainty,'unknown');
  assert.equal(result.job_id,'original_job');assert.equal(result.session_ref,'original_session');
  assert.equal(result.error.reason,'service_stdio_drain_unconfirmed');
  child.stdout.write(JSON.stringify({id:'tb_1',result:{state:'succeeded'}})+'\n');
  finish(child,3);
  assert.equal(child.writes.length,1);assert.equal(result.state,'unknown');
});

test('request timeout retains immutable original request ID through late reply',async()=>{
  const {child,bridge}=fixture({requestTimeoutMs:10});
  const args={api_version:'mdc.toolbox/1',request_id:'original_observe',session_ref:'original_session',profile:'player'};
  const pending=bridge.call('mdc_observe',args);args.request_id='changed-by-caller';
  const result=await pending;
  assert.equal(result.state,'unknown');assert.equal(result.request_id,'original_observe');
  child.stdout.write(JSON.stringify({id:'tb_1',result:{job_id:'late_original_job'}})+'\n');
  child.emit('exit',0,null);finish(child);
  assert.equal(child.writes.length,1);assert.equal(bridge.pending.size,0);
});

test('transport envelope error retains exact original identity',async()=>{
  const {child,bridge}=fixture();
  const pending=bridge.call('mdc_job',request);
  child.stdout.write(JSON.stringify({id:'tb_1',error:{code:'synthetic_error'}})+'\n');
  const result=await pending;
  assert.equal(result.job_id,'original_job');assert.equal(result.state,'unknown');
  assert.equal(result.error.reason,'service_error_response');
  child.emit('exit',0,null);finish(child);
});

test('malformed tail never claims success or invents a replacement identity',async()=>{
  const {child,bridge}=fixture();
  const pending=bridge.call('mdc_job',request);
  child.emit('exit',3,null);child.stdout.write('{not-json}\n');finish(child,3);
  const result=await pending;
  assert.equal(result.job_id,'original_job');assert.equal(result.state,'unknown');
  assert.equal(result.error.reason,'malformed_service_response');assert.equal(child.writes.length,1);
});

test('new calls during drain are not dispatched',async()=>{
  const {child,bridge}=fixture();
  child.emit('exit',0,null);
  const result=await bridge.call('mdc_job',request);
  assert.equal(result.state,'blocked');assert.equal(child.writes.length,0);
  finish(child);
});
