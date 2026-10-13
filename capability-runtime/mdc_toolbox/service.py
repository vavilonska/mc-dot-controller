"""Four-tool façade over one injected owner backend; no native transport here."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import threading
import time
import uuid
from .catalog import CapabilityCatalog
from .contracts import (API_VERSION, ToolboxError, validate_call, validate_schema, json_data, STATES,
                        EFFECT_CERTAINTIES, CLEANUP_CERTAINTIES, TERMINAL)
from .jobs import JobStore
from .serialization import public_data, serialize_outcome

class UnavailableBackend:
    def describe(self):
        return {'available':False,'private_singleplayer':False,'session_ref':None,'context_ref':None,
                'supported_capabilities':[],'native_features':[],'supported_budget_metrics':[],
                'cancellation_supported':False,'reason':'Operator runtime binding not configured'}
    def observe(self,*_): raise ToolboxError('observation_unavailable','Runtime not configured',stage='observation')
    def execute(self,*_): raise ToolboxError('capability_unavailable','Runtime not configured',stage='admission')
    def cancel_exact(self,*_): raise ToolboxError('cancel_unconfirmed','Runtime not configured',stage='cancel',effect_certainty='unknown')
    def reconcile_original(self,*_): raise ToolboxError('outcome_unknown','Runtime not configured',stage='reconcile',effect_certainty='unknown')

class ToolboxService:
    def __init__(self,backend,journal_directory,*,catalog=None,start_workers=True):
        self.backend=backend or UnavailableBackend()
        self.capabilities=catalog or CapabilityCatalog()
        self.store=JobStore(journal_directory)
        self._lock=threading.RLock(); self._condition=threading.Condition(self._lock)
        self._workers={}; self._cancel_events={}; self._cancel_workers={}
        self._start_workers=start_workers; self._closing=False; self._closed=False; self.shutdown_result=None

    def call(self,tool_name,arguments):
        try:
            args=validate_call(tool_name,arguments)
            result=getattr(self,tool_name.removeprefix('mdc_'))(args)
            result=public_data(result); json_data(result)
            return result
        except ToolboxError as exc:
            return {'api_version':API_VERSION,'error':exc.as_dict()}
        except Exception:
            # Exception text may contain private host paths or credentials.
            return {'api_version':API_VERSION,'error':ToolboxError('internal_error','Toolbox operation failed; query original identity before any new action',stage='service',effect_certainty='unknown',suggested_next_operation='status').as_dict()}

    def _description(self):
        value=public_data(self.backend.describe()); json_data(value)
        if not isinstance(value,dict): raise ToolboxError('runtime_unavailable','Invalid backend description',stage='admission')
        return value

    def catalog(self,args): return self.capabilities.page(args,self._description())

    def _session(self,args,description):
        if description.get('available') is not True: raise ToolboxError('capability_unavailable','Runtime unavailable',stage='admission')
        if args['session_ref']!=description.get('session_ref'): raise ToolboxError('context_changed','Session reference does not match bound runtime',stage='admission')
        if description.get('private_singleplayer') is not True: raise ToolboxError('policy_violation','Private singleplayer is not verified',stage='admission')

    def observe(self,args):
        description=self._description(); self._session(args,description)
        if args.get('acquisition_profile') and args['acquisition_profile'] not in description.get('acquisition_profiles',[]):
            raise ToolboxError('observation_unavailable','Acquisition profile unavailable',stage='observation')
        # Fresh reads cannot race or invalidate an active mutation's preflight.
        with self._lock:
            if self._busy(): raise ToolboxError('owner_busy','Fresh observation blocked while owner job is active or uncertain',stage='observation')
            bounds=deepcopy(args.get('bounds',{}))
            if 'acquisition_profile' in args: bounds['acquisition_profile']=args['acquisition_profile']
            try:
                result=public_data(self.backend.observe(args['profile'],deepcopy(args.get('selectors',{})),bounds))
            except ToolboxError:raise
            except Exception as exc:
                unknown=getattr(exc,'status',None)=='unknown'
                raise ToolboxError('outcome_unknown' if unknown else 'observation_unavailable',
                                   'Backend observation unavailable or unsupported',stage='observation',
                                   effect_certainty='unknown' if unknown else 'none_proven') from None
        if not isinstance(result,dict): raise ToolboxError('observation_unavailable','Invalid observation result',stage='observation')
        result.update(api_version=API_VERSION,executable_authority=False,server_confirmed=False)
        result.setdefault('warnings',[])
        # Never invent coverage, capture age or source clock when omitted.
        result.setdefault('coverage',{'status':'unknown'})
        result.setdefault('provenance',{'status':'unavailable'})
        return result

    def plan(self,args):
        definition=self.capabilities.validate(args['capability'],args['capability_version'],args['arguments'])
        result={'api_version':API_VERSION,'plan_id':'plan_'+uuid.uuid4().hex,'capability':args['capability'],
                'validated_intent':deepcopy(args['arguments']),'prerequisites':deepcopy(definition['prerequisites']),
                'steps':[],'materials':[],'assumptions':['Planning does not establish fresh action admission'],
                'estimates':{},'blockers':[],'executable_authority':False,'server_confirmed':False}
        plugin=self.capabilities.plugin(args['capability'])
        if not definition.get('planner_available') or plugin is None:
            result.update(status='preview_unsupported',blockers=['preview_unsupported']); return result
        # Only closed domain pure planners are callable; no runtime is supplied.
        planned=public_data(plugin.plan(args['capability'],deepcopy(args['arguments']),observation=None))
        if not isinstance(planned,dict): raise ToolboxError('preview_unsupported','Planner returned invalid data',stage='plan')
        result.update(planned); result['executable_authority']=False; result['server_confirmed']=False
        return result

    def job(self,args):
        return getattr(self,'_'+args['operation'])(args)

    def _busy(self):
        return any(r['state'] in ('accepted','running','stopping','unknown') or r['cleanup_certainty'] in ('pending','unknown')
                   for r in self.store.all())

    @staticmethod
    def _digest(args,exclude=()):
        return hashlib.sha256(json_data({k:v for k,v in args.items() if k not in exclude})).hexdigest()

    def _public_job(self,record,cursor=0):
        events,gap=self.store.event_page(record['job_id'],cursor)
        result={k:deepcopy(v) for k,v in record.items() if k not in ('intent','backend_context','dispatch_started','cancel_requested','cancel_sent')}
        result.update(events=events,event_gap=gap,server_confirmed=False)
        return result

    def _lookup(self,args):
        record=self.store.get(job_id=args.get('job_id'),request_id=args.get('request_id'))
        if record is None: raise ToolboxError('job_not_found','No job with the exact identity',stage='lookup')
        if record['session_ref']!=args['session_ref']: raise ToolboxError('context_changed','Job belongs to another session',stage='lookup')
        return record

    def _submit(self,args):
        digest=self._digest(args,('wait_ms',))
        with self._lock:
            existing=self.store.get(request_id=args['request_id'])
            if existing:
                if existing['intent_digest']!=digest: raise ToolboxError('request_conflict','Request ID already binds a different immutable intent',stage='admission')
                return self._public_job(existing)
            if self._closing: raise ToolboxError('service_stopping','Service is stopping',stage='admission')
            description=self._description(); self._session(args,description)
            if args['expected_context_ref']!=description.get('context_ref'):
                raise ToolboxError('context_changed','Expected context does not match current runtime',stage='admission')
            definition=self.capabilities.validate(args['capability'],args['capability_version'],args['arguments'])
            available=self.capabilities.entry(args['capability'],description)
            if not available['runtime_available']:
                raise ToolboxError('capability_unavailable',available['availability_reason'],stage='admission')
            requested=set(args['budgets'])-{'deadline_seconds'}
            supported=set(description.get('supported_budget_metrics',[]))
            if requested-supported: raise ToolboxError('invalid_request','Requested budget metric is unsupported',stage='admission')
            policies=description.get('supported_policies',{})
            if args['policy'].get('reactions','stop')!='stop' and args['policy'].get('reactions') not in policies.get('reactions',[]):
                raise ToolboxError('policy_violation','Requested reaction policy is unsupported',stage='admission')
            if self._busy(): raise ToolboxError('owner_busy','The existing owner job must settle before another admission',stage='admission')
            deadline=time.time()+args['budgets']['deadline_seconds']
            budget={k:v for k,v in args['budgets'].items() if k!='deadline_seconds'}
            budget.setdefault('max_observations',1024)
            budget.setdefault('reflex_reserve_actions',0)
            budget.setdefault('cleanup_reserve_actions',1)
            if budget['reflex_reserve_actions']+budget['cleanup_reserve_actions']>budget['max_actions']:
                raise ToolboxError('budget_exhausted','Default cleanup reserve exceeds the original total',stage='admission')
            if definition['level']!='query' and budget['cleanup_reserve_actions']<1:
                raise ToolboxError('budget_exhausted','A mutation must reserve an exact native stop action',stage='admission')
            if definition['level']!='query' and budget['max_actions']<=budget['reflex_reserve_actions']+budget['cleanup_reserve_actions']:
                raise ToolboxError('budget_exhausted','Mutation requires ordinary allowance plus original cleanup reserve',stage='admission')
            job_id='job_'+uuid.uuid4().hex
            context={'job_id':job_id,'request_id':args['request_id'],'deadline_at':deadline,'budget':budget,
                     'policy':deepcopy(args['policy']),'expected_context':args['expected_context_ref']}
            record={'api_version':API_VERSION,'job_id':job_id,'request_id':args['request_id'],'intent_digest':digest,
                    'session_ref':args['session_ref'],'capability':args['capability'],'capability_version':args['capability_version'],
                    'build_versions':description.get('build_versions',{}),'context':{'context_ref':args['expected_context_ref']},
                    'owner_generation':None,'state':'accepted','phase':'accepted','event_cursor':0,'deadline':deadline,
                    'budgets':{**deepcopy(budget),'deadline_seconds':args['budgets']['deadline_seconds']},'active_action':None,'request_ids':[],'effect_certainty':'none_proven',
                    'cleanup_certainty':'not_needed','confirmed_effects':[],'goal_result':None,'result':None,'evidence':{},
                    'input_release':None,'ownership':None,'error':None,'continuation':'none','intent':deepcopy(args),
                    'backend_context':context,'dispatch_started':False,'cancel_requested':False,'cancel_sent':False}
            record=self.store.create(record)
            self._cancel_events[job_id]=threading.Event()
            if self._start_workers:
                worker=threading.Thread(target=self._run,args=(job_id,),daemon=True,name='mdc-toolbox-job')
                self._workers[job_id]=worker; worker.start()
        return self._wait_job(job_id,args.get('wait_ms',0))

    def _emit(self,job_id,event,payload):
        value=public_data(payload); json_data(value)
        if not isinstance(event,str) or len(event)>80 or not isinstance(value,dict):
            raise ToolboxError('invalid_backend_event','Invalid event',stage='execution',effect_certainty='unknown')
        with self._lock:
            if self._closed: raise ToolboxError('service_stopping','Service is closed',stage='execution',effect_certainty='unknown')
            record=self.store.get(job_id=job_id)
            if event=='owner_context':
                owner=value.get('owner_context',value)
                record['backend_context']['owner_context']=deepcopy(owner)
                record['context']['owner_context']=deepcopy(owner)
                ids=value.get('request_ids',owner.get('original_request_ids',[]))
                if isinstance(ids,list): record['request_ids']=list(dict.fromkeys(record['request_ids']+ids))
                record['backend_context']['request_ids']=deepcopy(record['request_ids'])
                record['owner_generation']=owner.get('owner_generation',record.get('owner_generation'))
            if 'active_action' in value: record['active_action']=value['active_action']
            record['phase']=event
            self.store.save(record,event,value); self._condition.notify_all()

    def _run(self,job_id):
        with self._lock:
            record=self.store.get(job_id=job_id)
            if record['state']!='accepted' or self._closing:return
            if time.time()>=record['deadline']:
                record.update(state='blocked',phase='deadline_exceeded',continuation='fresh_replan_required')
                self.store.save(record,'deadline_exceeded'); self._condition.notify_all(); return
            record.update(state='running',phase='dispatching',dispatch_started=True,cleanup_certainty='pending')
            record=self.store.save(record,'dispatch_started')
            context=deepcopy(record['backend_context'])
            context['cancel_event']=self._cancel_events[job_id]
            context['emit']=lambda event,payload:self._emit(job_id,event,payload)
        try:
            outcome=self.backend.execute(record['capability'],deepcopy(record['intent']['arguments']),context)
            with self._lock:
                if not self._closed:self._apply(job_id,outcome,'execution_result')
        except BaseException as exc:
            with self._lock:
                if not self._closed:self._unknown(job_id,'Backend execution did not return a proven outcome','execution_exception')
        finally:
            with self._lock:self._condition.notify_all()

    def _unknown(self,job_id,reason,event):
        record=self.store.get(job_id=job_id)
        record.update(state='unknown',phase=event,cleanup_certainty='unknown',continuation='reconcile_original_id_required')
        if record['effect_certainty']!='known': record['effect_certainty']='unknown'
        record['error']=ToolboxError('outcome_unknown',reason,stage=event,effect_certainty=record['effect_certainty'],
                                     affected_ids=record['request_ids'],suggested_next_operation='reconcile').as_dict()
        self.store.save(record,event); self._condition.notify_all()

    def _apply(self,job_id,outcome,event):
        outcome=public_data(outcome); json_data(outcome)
        record=self.store.get(job_id=job_id)
        if not isinstance(outcome,dict) or outcome.get('state') not in STATES or outcome.get('effect_certainty') not in EFFECT_CERTAINTIES or outcome.get('cleanup_certainty') not in CLEANUP_CERTAINTIES:
            self._unknown(job_id,'Backend certainty contract invalid',event); return
        if (event=='cancel_result' and record['state'] in TERMINAL and record['state']!='unknown'
                and record['cleanup_certainty'] in ('confirmed','not_needed')
                and outcome['state'] in ('accepted','running','stopping')
                and outcome['cleanup_certainty']=='pending'):
            # An acknowledgement begun before final execution proof cannot put a
            # settled owner back into motion. A genuine UNKNOWN cancellation
            # result is deliberately not covered by this acknowledgement case.
            self.store.save(record,'late_cancel_ack',{'state':outcome['state'],'cleanup_certainty':'pending'})
            self._condition.notify_all();return
        original_context=outcome.get('context',{})
        if isinstance(original_context,dict) and any(original_context.get(k,record[k])!=record[k] for k in ('job_id','request_id')):
            self._unknown(job_id,'Backend result belongs to another original identity',event);return
        if event=='reconcile_result' and any(identity not in record['request_ids'] for identity in outcome.get('request_ids',[])):
            self._unknown(job_id,'Reconciliation returned an unbound request identity',event);return
        if outcome.get('result') is not None:
            try:validate_schema(outcome['result'],self.capabilities.get(record['capability'])['result_schema'])
            except ToolboxError:
                self._unknown(job_id,'Domain result does not match advertised schema',event);return
        previous_goal=record.get('goal_result')
        previous_effect=record['effect_certainty']
        previous_result=deepcopy(record.get('result'))
        previous_evidence=deepcopy(record.get('evidence',{}))
        for key in ('state','effect_certainty','cleanup_certainty','result','evidence','confirmed_effects','goal_result','input_release','ownership','owner_generation','active_action'):
            if key in outcome:record[key]=deepcopy(outcome[key])
        if previous_goal is not None and record.get('goal_result') is None:record['goal_result']=previous_goal
        if previous_effect=='known' and (record['effect_certainty']=='none_proven' or event=='reconcile_result'):
            record['effect_certainty']='known'
        if previous_result is not None and record.get('result') is None:record['result']=previous_result
        if event in ('cancel_result','reconcile_result') and isinstance(previous_evidence,dict) and isinstance(record.get('evidence'),dict):
            record['evidence']={**previous_evidence,**record['evidence']}
        if event=='reconcile_result' and record['state'] in ('accepted','running','stopping'):
            record['state']='unknown'  # Original remote work pending; never create a resumed worker.
        if 'context' in outcome and isinstance(outcome['context'],dict):
            record['backend_context'].update(deepcopy(outcome['context']))
            if 'owner_context' in outcome['context']:record['context']['owner_context']=deepcopy(outcome['context']['owner_context'])
        ids=outcome.get('request_ids',[])
        if isinstance(ids,list):record['request_ids']=list(dict.fromkeys(record['request_ids']+ids))
        if record.get('goal_result') is None and (record['state']=='succeeded' or
                (isinstance(record.get('result'),dict) and record['result'].get('status')=='succeeded' and record['effect_certainty']=='known')):
            record['goal_result']=deepcopy(record.get('result'))
        # Known semantic success does not imply lease/input cleanup success.
        if record['cleanup_certainty'] in ('pending','unknown') and record['state'] in TERMINAL:
            record['state']='unknown'
        if record['state']=='unknown':record['continuation']='reconcile_original_id_required'
        elif record['state'] in ('blocked','failed','interrupted'):record['continuation']='fresh_replan_required'
        else:record['continuation']='none'
        record['phase']=event
        if outcome.get('error'):record['error']=deepcopy(outcome['error'])
        elif outcome.get('reason') and record['state'] not in ('succeeded','cancelled'):
            record['error']=ToolboxError('outcome_unknown' if record['state']=='unknown' else 'known_action_failure',
                                         str(outcome['reason'])[:512],stage=event,effect_certainty=record['effect_certainty'],affected_ids=record['request_ids'],
                                         suggested_next_operation='reconcile' if record['state']=='unknown' else None).as_dict()
        else:record['error']=None
        self.store.save(record,event,{'state':record['state']});self._condition.notify_all()

    def _wait_job(self,job_id,wait_ms,cursor=0):
        stop=time.monotonic()+wait_ms/1000
        with self._condition:
            while True:
                record=self.store.get(job_id=job_id)
                remaining=stop-time.monotonic()
                if record['state'] in TERMINAL or remaining<=0:return self._public_job(record,cursor)
                self._condition.wait(remaining)

    def _status(self,args):
        with self._lock:record=self._lookup(args)
        return self._wait_job(record['job_id'],args.get('wait_ms',0),args.get('event_cursor',0))

    def _cancel(self,args):
        with self._lock:
            record=self._lookup(args); job_id=record['job_id']
            fresh=self.store.bind_cancel(args['cancel_request_id'],job_id,self._digest(args,('wait_ms',)))
            if not fresh:return self._public_job(record)
            if record['state'] in TERMINAL:return self._public_job(record)
            record['cancel_requested']=True
            self._cancel_events.setdefault(job_id,threading.Event()).set()
            if not record['dispatch_started']:
                record.update(state='cancelled',phase='cancelled_before_dispatch',effect_certainty='none_proven',cleanup_certainty='not_needed',continuation='none')
                self.store.save(record,'cancelled_before_dispatch');self._condition.notify_all();return self._public_job(self.store.get(job_id=job_id))
            record.update(state='stopping',phase='cancel_requested')
            self.store.save(record,'cancel_requested',{'cancel_request_id':args['cancel_request_id']})
            owner=record['backend_context'].get('owner_context')
            if not owner:
                # The worker sees cancel_event at its next checkpoint. Never send
                # an unbound native cancel or infer neutral controls.
                self._unknown(job_id,'Exact owner is not yet durably known','cancel_owner_unknown')
                return self._public_job(self.store.get(job_id=job_id))
            if record.get('cancel_sent'):
                return self._public_job(record)
            record['cancel_sent']=True
            self.store.save(record,'cancel_dispatch_started')
            worker=threading.Thread(target=self._cancel_backend,args=(job_id,args['cancel_request_id']),daemon=True,name='mdc-toolbox-cancel')
            self._cancel_workers[job_id]=worker;worker.start()
        return self._wait_job(job_id,args.get('wait_ms',0))

    def _cancel_backend(self,job_id,cancel_id):
        with self._lock:context=deepcopy(self.store.get(job_id=job_id)['backend_context'])
        try:
            outcome=self.backend.cancel_exact(context,cancel_id)
            with self._lock:
                if not self._closed:self._apply(job_id,outcome,'cancel_result')
        except BaseException:
            with self._lock:
                if not self._closed:self._unknown(job_id,'Exact cancellation was not confirmed','cancel_unknown')

    def _reconcile(self,args):
        with self._lock:
            record=self._lookup(args)
            if not record['dispatch_started'] or record['state'] not in ('unknown','interrupted'):
                return self._public_job(record)
            context=deepcopy(record['backend_context'])
        try:outcome=self.backend.reconcile_original(context)
        except Exception:
            with self._lock:
                self._unknown(record['job_id'],'Original evidence reconciliation unavailable','reconcile_unknown')
                return self._public_job(self.store.get(job_id=record['job_id']))
        with self._lock:
            self._apply(record['job_id'],outcome,'reconcile_result')
            return self._public_job(self.store.get(job_id=record['job_id']))

    def shutdown(self,timeout=2):
        """Bounded exact-owner stop. Unconfirmed work stays durable and quarantined."""
        with self._lock:
            if self._closed:return self.shutdown_result
            self._closing=True
            records=self.store.all()
        for record in records:
            if record['state'] in ('accepted','running','stopping'):
                self._cancel({'api_version':API_VERSION,'operation':'cancel','session_ref':record['session_ref'],'job_id':record['job_id'],
                              'cancel_request_id':'shutdown_'+uuid.uuid4().hex,'reason':'service_shutdown'})
        deadline=time.monotonic()+timeout
        for worker in list(self._workers.values())+list(self._cancel_workers.values()):
            if worker is not threading.current_thread():worker.join(max(0,deadline-time.monotonic()))
        with self._lock:
            for record in self.store.all():
                if record['state'] in ('accepted','running','stopping'):
                    self._unknown(record['job_id'],'Service stopped before terminal cleanup proof','shutdown_unknown')
            unresolved=[r['job_id'] for r in self.store.all() if r['state']=='unknown' or r['cleanup_certainty'] in ('unknown','pending')]
            self.shutdown_result={'cleanup_confirmed':not unresolved,'unresolved_job_ids':unresolved}
            self._closed=True;self.store.close()
            return deepcopy(self.shutdown_result)

    close=shutdown
