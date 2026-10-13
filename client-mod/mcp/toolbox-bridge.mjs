/** Operator-bound stdio transport for the existing Python toolbox/owner stack.
 * This does not start Minecraft, create credentials, listen on a socket or retry.
 */
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';

export const TOOLBOX_NAMES = Object.freeze(['mdc_catalog','mdc_observe','mdc_plan','mdc_job']);
export const LEGACY_MUTATORS = Object.freeze(['minecraft_client_launch','minecraft_client_register','minecraft_client_action','minecraft_client_input','minecraft_client_close']);
const MAX_BYTES=1024*1024, MAX_PENDING=32;
const exact=(v,keys)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const fail=(code,reason,effect='none_proven')=>({api_version:'mdc.toolbox/1',state:effect==='unknown'?'unknown':'blocked',effect_certainty:effect,cleanup_certainty:effect==='unknown'?'unknown':'not_needed',error:{code,stage:'toolbox_transport',reason,effect_certainty:effect,affected_ids:[],suggested_next_operation:effect==='unknown'?'status_original_request':'inspect_configuration'},continuation:effect==='unknown'?'reconcile_original_id_required':'none'});
function finite(value,depth=0){
  if(depth>40)return false;
  if(typeof value==='number')return Number.isFinite(value);
  if(value===null||typeof value==='string'||typeof value==='boolean')return true;
  if(Array.isArray(value))return value.every(v=>finite(v,depth+1));
  if(typeof value==='object')return Object.values(value).every(v=>finite(v,depth+1));
  return false;
}
export function loadToolboxConfiguration(filename,sourceRoot){
  if(!path.isAbsolute(filename)||!path.isAbsolute(sourceRoot))throw new Error('absolute_operator_configuration_required');
  const stat=fs.lstatSync(filename);
  if(!stat.isFile()||stat.isSymbolicLink()||stat.size>65536)throw new Error('invalid_operator_configuration_file');
  const config=JSON.parse(fs.readFileSync(filename,'utf8'));
  const keys=['schema_version','python_executable','python_sha256','control_directory','journal_directory','runtime_journal_directory'];
  if(!exact(config,keys)||config.schema_version!==1||!(/^[a-f0-9]{64}$/).test(config.python_sha256))throw new Error('invalid_operator_configuration');
  for(const key of keys.filter(k=>k.endsWith('_directory')||k==='python_executable'))if(typeof config[key]!=='string'||!path.isAbsolute(config[key])||config[key].includes('\0'))throw new Error('invalid_operator_path');
  const dirs=keys.filter(k=>k.endsWith('_directory')).map(k=>path.resolve(config[k]));
  for(let i=0;i<dirs.length;i++)for(let j=i+1;j<dirs.length;j++)if(dirs[i]===dirs[j]||dirs[i].startsWith(dirs[j]+path.sep)||dirs[j].startsWith(dirs[i]+path.sep))throw new Error('operator_directories_must_be_disjoint');
  const executable=fs.realpathSync(config.python_executable), st=fs.statSync(executable);
  if(!st.isFile()||st.size>128*1024*1024||createHash('sha256').update(fs.readFileSync(executable)).digest('hex')!==config.python_sha256)throw new Error('python_identity_mismatch');
  return Object.freeze({...config,python_executable:executable,source_root:fs.realpathSync(sourceRoot)});
}
export class ToolboxBridge {
  constructor(child,{requestTimeoutMs=15000}={}){
    this.child=child;this.requestTimeoutMs=requestTimeoutMs;this.pending=new Map();this.sequence=0;this.buffer=Buffer.alloc(0);this.terminal=false;this.closed=false;this.protocolFailure=false;this.terminalResult=null;
    this.exitPromise=new Promise(resolve=>{this.resolveExit=resolve;});
    child.stdout.on('data',chunk=>this.onData(chunk));
    child.stderr?.on('data',()=>{}); // No private runtime diagnostics are copied to public results.
    child.on('error',()=>this.onTerminal(null,'service_process_error'));
    child.on('exit',(code,signal)=>this.onTerminal(code,signal?'service_signalled':'service_exited'));
    child.stdin.on('error',()=>this.onTerminal(null,'service_input_closed'));
  }
  onTerminal(code,reason){
    if(this.terminal)return;
    this.terminal=true;this.terminalResult={exit_code:code,reason};
    for(const [id,p] of this.pending){clearTimeout(p.timer);p.resolve(fail('outcome_unknown',reason,'unknown'));}
    this.pending.clear();this.resolveExit(this.terminalResult);
  }
  onData(chunk){
    if(this.terminal||this.protocolFailure)return;
    this.buffer=Buffer.concat([this.buffer,Buffer.from(chunk)]);
    for(;;){
      const ix=this.buffer.indexOf(10);
      if((ix<0&&this.buffer.length>MAX_BYTES)||ix>MAX_BYTES){this.protocolError();return;}
      if(ix<0)return;
      const bytes=this.buffer.subarray(0,ix);this.buffer=this.buffer.subarray(ix+1);
      let message;
      try{message=JSON.parse(bytes.toString('utf8'));}catch{this.protocolError();return;}
      if(!finite(message)||!message||typeof message!=='object'||Array.isArray(message)||typeof message.id!=='string'||Object.keys(message).some(k=>!['id','result','error'].includes(k))||Object.hasOwn(message,'result')===Object.hasOwn(message,'error')){this.protocolError();return;}
      const p=this.pending.get(message.id);
      // Timed-out or already consumed IDs are never reused and cannot alter later calls.
      if(!p)continue;
      this.pending.delete(message.id);clearTimeout(p.timer);
      p.resolve(Object.hasOwn(message,'result')?message.result:fail('outcome_unknown','service_error_response','unknown'));
    }
  }
  protocolError(){
    this.protocolFailure=true;
    for(const [id,p] of this.pending){clearTimeout(p.timer);p.resolve(fail('outcome_unknown','malformed_service_response','unknown'));}
    this.pending.clear();
    // EOF invokes the service's owner-aware stop. Never kill/restart/replay here.
    this.child.stdin.end();
  }
  call(tool,args){
    if(!TOOLBOX_NAMES.includes(tool))return Promise.resolve(fail('invalid_request','unknown_toolbox_tool'));
    if(this.closed||this.terminal||this.protocolFailure)return Promise.resolve(fail('capability_unavailable','toolbox_service_unavailable'));
    if(this.pending.size>=MAX_PENDING)return Promise.resolve(fail('owner_busy','toolbox_transport_capacity'));
    if(!finite(args))return Promise.resolve(fail('invalid_request','invalid_json_arguments'));
    const id='tb_'+(++this.sequence);
    let body;
    try{body=JSON.stringify({id,tool,arguments:args})+'\n';}catch{return Promise.resolve(fail('invalid_request','invalid_json_arguments'));}
    if(Buffer.byteLength(body)>MAX_BYTES)return Promise.resolve(fail('invalid_request','toolbox_request_too_large'));
    return new Promise(resolve=>{
      const timer=setTimeout(()=>{if(!this.pending.has(id))return;this.pending.delete(id);resolve(fail('outcome_unknown','toolbox_transport_wait_expired','unknown'));},this.requestTimeoutMs);
      this.pending.set(id,{resolve,timer});
      try{this.child.stdin.write(body,error=>{if(error&&this.pending.has(id)){const p=this.pending.get(id);this.pending.delete(id);clearTimeout(p.timer);p.resolve(fail('outcome_unknown','toolbox_write_outcome_unknown','unknown'));}});}catch{const p=this.pending.get(id);this.pending.delete(id);clearTimeout(p.timer);p.resolve(fail('outcome_unknown','toolbox_write_outcome_unknown','unknown'));}
    });
  }
  async close({waitMs=10000}={}){
    if(!this.closed){this.closed=true;this.child.stdin.end();}
    if(this.terminal)return this.terminalResult;
    let timer;const pending=new Promise(resolve=>{timer=setTimeout(()=>resolve({exit_code:null,reason:'service_close_unconfirmed'}),waitMs);});
    const result=await Promise.race([this.exitPromise,pending]);clearTimeout(timer);return result;
  }
}
export function startConfiguredToolbox(config,{spawnFunction=spawn}={}){
  const root=config.source_root;
  const names=['capability-runtime','resident-controller','defense-watchdog','building-controller','navigation-controller','navigation-cursor','external-controller','multiagent-coordination','gameplay-helpers'];
  const env={PATH:path.dirname(config.python_executable),PYTHONDONTWRITEBYTECODE:'1',PYTHONNOUSERSITE:'1',PYTHONPATH:names.map(n=>path.join(root,n)).join(path.delimiter),LANG:'C.UTF-8'};
  const child=spawnFunction(config.python_executable,['-B','-m','mdc_toolbox','--control',config.control_directory,'--journal',config.journal_directory,'--runtime-journal',config.runtime_journal_directory],{cwd:root,env,stdio:['pipe','pipe','pipe'],windowsHide:true,shell:false});
  return new ToolboxBridge(child);
}
export function legacyMutationRefusal(name,configured){
  return configured&&LEGACY_MUTATORS.includes(name)?fail('owner_busy','toolbox_exclusive_operator_binding'):null;
}
