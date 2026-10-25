"""Explicit request-only rearm after a recorded clean GUI pause."""
from copy import deepcopy
import time
from resident_controller import pause_acknowledgment as proof
from resident_controller.ipc import read_json


def clear_owners(dog):
    return (dog.execution_policy=='request_only' and not dog.stop_requested and not dog.stopped
        and not dog.handoff_latched and not dog.input_release_latched and dog.owner is None
        and dog.capability_lease is None and dog.started_target is None
        and getattr(dog,'ranged_move',None) is None and not getattr(getattr(dog,'environment',None),'active',False)
        and all(getattr(dog,k,None) is None for k in ('_fall_rescue_owner','_external_navigation_owner','_managed_navigation_owner','_coordination_owner'))
        and not any(type(v) is not dict or v.get('pending') is not None for v in getattr(dog,'_fall_adjudications',{}).values())
        and (dog.rpc is None or dog.rpc.get('kind') in ('observe','fresh')))

def neutral(value):
    from capability_ownership import safe_idle,safe_policy
    from resident_controller.action_safety import native_release_unconfirmed,task_handoff_required
    if not safe_idle(value) or not safe_policy(value.get('resident_policy')):return False
    state=value.get('state',{})
    for action in (value.get('action'),state.get('client_action')):
        if not isinstance(action,dict) or native_release_unconfirmed(action) or task_handoff_required(action):return False
        for part in (action,action.get('result',{})):
            if not isinstance(part,dict):return False
            if any(k in part and part[k] is not False for k in ('unknown_outcome','uncertain','post_uncertain','requires_handoff','input_release_unconfirmed','unknown_outcome_quarantined','automation_blocked')):return False
    if 'native_fall_rescue' in state or 'native_fall_rescue_status' in state:
        fall=state.get('native_fall_rescue_status',{})
        if any(fall.get(k) is not False for k in ('armed','input_owned','automation_blocked','unknown_outcome_quarantined')):return False
    return True

def observation(dog,rpc,result):
    """Remember only an exact new ordinary readonly receipt; no authority change."""
    dog._pause_ack_sample=None
    if (result.get('status')=='succeeded' and result.get('request_id')==rpc.get('id')
            and type(rpc.get('resident_session')) is str and result.get('session_id')==rpc['resident_session']):
        dog._pause_ack_sample={'request_id':rpc['id'],'resident_session':rpc['resident_session'],
            'bridge_identity':deepcopy(rpc.get('resident_bridge')),'started':rpc['started'],
            'payload':dog.latest,'received':dog.clock()}

def remember(dog,reason,was_armed):
    from capability_ownership import safe_idle,safe_policy,context_of,integrated_server_instance_of
    dog._pause_ack_origin=None
    sample=getattr(dog,'_pause_ack_sample',None);value=deepcopy(dog.latest or {});state=value.get('state',{})
    if (not was_armed or reason!=proof.REASON or not clear_owners(dog) or sample is None
            or sample['payload'] is not dog.latest or state.get('paused') is not True or state.get('screen_open') is not True):return
    state['paused']=False
    context=context_of(state);server=integrated_server_instance_of(state);tick=state.get('world',{}).get('game_time')
    if not neutral(value) or not context or not server or type(tick) is not int:return
    dog._pause_ack_origin={'watchdog_session':dog.session_id,'defense_epoch':dog.defense_epoch,'reason':reason,
        'context':context,'integrated_server_instance':server,'resident_session':sample['resident_session'],
        'bridge_identity':deepcopy(sample['bridge_identity']),'pause_tick':tick}

def status(dog):
    origin=getattr(dog,'_pause_ack_origin',None)
    eligible=(origin is not None and not dog.armed and dog.reason==proof.REASON and clear_owners(dog)
        and origin['defense_epoch']==dog.defense_epoch and origin['watchdog_session']==dog.session_id)
    return {'version':proof.VERSION,'eligible':eligible,'pause_ref':proof.digest(origin) if eligible else None,
        'pending':getattr(dog,'_pause_ack_pending',None) is not None,'new_requests_only':True,'automatic_resume':False}

def finish(dog,pending,success,reason):
    p={'schema_version':1,'command':deepcopy(pending['command']),'request_sha256':proof.digest(pending['command']),
       'rearmed':success,'origin':deepcopy(pending['origin']) if success else None,
       'samples':deepcopy(pending['samples']) if success else [],'no_task_resume':True,'no_native_mutation':True}
    dog.capability_complete(pending['id'],'succeeded' if success else 'failed',reason,pause_acknowledgment=p)
    if getattr(dog,'_pause_ack_pending',None) is pending:dog._pause_ack_pending=None

def submit(dog,request_id,command):
    proof.command(command)
    p={'id':request_id,'command':deepcopy(command),'origin':deepcopy(getattr(dog,'_pause_ack_origin',None)),
       'accepted':dog.clock(),'deadline':dog.clock()+max(0,command['expires_at']-time.time()),'samples':[],'last_sample':None}
    now=time.time()
    if (not status(dog)['eligible'] or status(dog)['pause_ref']!=command['pause_ref']
            or command['expected_defense_epoch']!=dog.defense_epoch or getattr(dog,'_pause_ack_pending',None) is not None
            or not 0<=now-command['created_at']<5 or now>=command['expires_at']):
        finish(dog,p,False,'pause_ack_not_eligible');return True
    dog._pause_ack_pending=p
    dog.next_observe=0
    return True

def no_pending_commands(dog,request_id):
    root=getattr(dog,'capability_directory',None)
    if root is None:return False
    for name in ('inbox','working'):
        for path in (root/name).glob('*.json'):
            if path.stem!=request_id:return False
    return not (root/'STOP').exists()

def tick(dog):
    from capability_ownership import safe_idle,safe_policy,context_of,integrated_server_instance_of
    p=getattr(dog,'_pause_ack_pending',None)
    if p is None:return
    o=p['origin'];sample=getattr(dog,'_pause_ack_sample',None)
    def current():
        return (getattr(dog,'_pause_ack_pending',None) is p and clear_owners(dog) and not dog.armed
            and dog.reason==proof.REASON and dog.defense_epoch==o['defense_epoch'] and dog.session_id==o['watchdog_session']
            and proof.exact(getattr(dog,'_pause_ack_origin',None),o) and dog.clock()<p['deadline'])
    if not current():finish(dog,p,False,'pause_ack_scope_changed_or_expired');return
    if sample is None or sample['request_id']==p['last_sample'] or sample['started']<p['accepted']:return
    p['last_sample']=sample['request_id'];value=dog.latest;state=value.get('state',{})
    if (sample['payload'] is not value or sample['resident_session']!=o['resident_session']
            or not proof.exact(sample['bridge_identity'],o['bridge_identity'])
            or not proof.exact(context_of(state),o['context']) or integrated_server_instance_of(state)!=o['integrated_server_instance']):
        finish(dog,p,False,'pause_ack_observation_identity_changed');return
    tick_value=state.get('world',{}).get('game_time')
    if (not neutral(value) or state.get('screen_open') is not False
            or type(tick_value) is not int or not 0<=dog.clock()-sample['received']<=.8):
        p['samples']=[];return
    if tick_value<=(p['samples'][-1]['tick'] if p['samples'] else o['pause_tick']):return
    p['samples'].append({'request_id':sample['request_id'],'tick':tick_value})
    if len(p['samples'])<2:return
    def final_binding():
        return proof.encode({'origin':p['origin'],'command':p['command'],'samples':p['samples'],
            'accepted':p['accepted'],'deadline':p['deadline'],
            'sample':{k:sample[k] for k in ('request_id','resident_session','bridge_identity','started','received')},
            'game_time':value['state']['world'].get('game_time')})
    frozen_binding=final_binding()
    try:
        resident=dog.q.session()
        if (resident.get('session_id')!=o['resident_session'] or not proof.exact(resident.get('bridge_identity'),o['bridge_identity'])
                or resident.get('state')!='ready' or resident.get('active_request_id') is not None or type(resident.get('pending')) is not int or resident['pending']!=0
                or resident.get('terrain_acquisition_unknown') is not None
                or not safe_policy(resident.get('resident_policy')) or not no_pending_commands(dog,p['id'])):
            finish(dog,p,False,'pause_ack_final_idle_unconfirmed');return
        # All I/O precedes this final same-object/epoch/context/age fence.
        if (final_binding()!=frozen_binding or not current() or dog.latest is not value or getattr(dog,'_pause_ack_sample',None) is not sample
                or not 0<=dog.clock()-sample['received']<=.8
                or not proof.exact(context_of(value.get('state')),o['context'])
                or integrated_server_instance_of(value['state'])!=o['integrated_server_instance']
                or value['state'].get('screen_open') is not False or not neutral(value)):
            finish(dog,p,False,'pause_ack_final_scope_changed');return
        dog.defense_epoch+=1
        dog.armed=True;dog.phase='watching';dog.reason='explicit_pause_acknowledged_new_requests_only'
        dog._pause_ack_origin=None
        finish(dog,p,True,dog.reason)
    except (ValueError,OSError,KeyError,TypeError):
        finish(dog,p,False,'pause_ack_final_read_unconfirmed')
