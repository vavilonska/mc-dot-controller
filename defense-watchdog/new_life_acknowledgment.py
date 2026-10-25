"""Explicit new-life rearm; a death fact is retained, never inferred from position."""
from copy import deepcopy
import math
import time
from resident_controller import new_life_acknowledgment as proof
from pause_acknowledgment import clear_owners as ordinary_clear_owners,neutral,no_pending_commands


def clear_owners(dog):
    return ordinary_clear_owners(dog) and getattr(dog,'_pause_ack_pending',None) is None

def observation(dog,rpc,result):
    dog._new_life_ack_sample=None
    if (result.get('status')=='succeeded' and result.get('request_id')==rpc.get('id')
            and type(rpc.get('resident_session')) is str and result.get('session_id')==rpc['resident_session']):
        dog._new_life_ack_sample={'request_id':rpc['id'],'resident_session':rpc['resident_session'],
            'bridge_identity':deepcopy(rpc.get('resident_bridge')),'started':rpc['started'],
            'payload':dog.latest,'received':dog.clock()}

def remember(dog,reason):
    """Retain the first actual dead observation, independent of a later epoch.
    This is evidence only: an in-flight owner or UNKNOWN cannot be released here.
    Repeated dead reads and healthy/menu reads never rewrite the retained fact.
    """
    from capability_ownership import context_of,integrated_server_instance_of
    if reason!=proof.REASON or getattr(dog,'_new_life_ack_origin',None) is not None:return
    sample=getattr(dog,'_new_life_ack_sample',None);value=dog.latest or {};state=value.get('state',{});player=state.get('player',{})
    generation=proof.generation(player);context=context_of(state);server=integrated_server_instance_of(state)
    health=player.get('health');tick=state.get('world',{}).get('game_time')
    if (sample is None or sample['payload'] is not value or not generation or not context or not server
            or state.get('private_singleplayer') is not True or player.get('alive') is not False
            or type(health) not in (int,float) or not math.isfinite(health) or health>0
            or type(tick) is not int or tick<0 or type(dog.defense_epoch) is not int or dog.defense_epoch<1):return
    dog._new_life_ack_origin={'watchdog_session':dog.session_id,'death_epoch':dog.defense_epoch,'reason':reason,
        'context':deepcopy(context),'integrated_server_instance':server,'resident_session':sample['resident_session'],
        'bridge_identity':deepcopy(sample['bridge_identity']),'death_request_id':sample['request_id'],
        'death_tick':tick,'dead_generation':generation,'death_health':health}

def candidate(dog,origin):
    from capability_ownership import context_of,integrated_server_instance_of
    sample=getattr(dog,'_new_life_ack_sample',None);value=dog.latest or {};state=value.get('state',{});player=state.get('player',{})
    generation=proof.generation(player);health=player.get('health')
    return (sample is not None and sample['payload'] is value and sample['resident_session']==origin['resident_session']
        and proof.exact(sample['bridge_identity'],origin['bridge_identity'])
        and proof.same_lifecycle(context_of(state),origin['context']) and integrated_server_instance_of(state)==origin['integrated_server_instance']
        and generation is not None and generation!=origin['dead_generation'] and player.get('alive') is True
        and type(health) in (int,float) and math.isfinite(health) and health>0)

def status(dog):
    origin=getattr(dog,'_new_life_ack_origin',None)
    eligible=(origin is not None and not dog.armed and dog.reason==proof.REASON and clear_owners(dog)
        and origin['watchdog_session']==dog.session_id and type(dog.defense_epoch) is int and dog.defense_epoch>=origin['death_epoch']
        and candidate(dog,origin))
    return {'version':proof.VERSION,'eligible':eligible,'death_ref':proof.digest(origin) if eligible else None,
        'pending':getattr(dog,'_new_life_ack_pending',None) is not None,'new_requests_only':True,'automatic_resume':False}

def finish(dog,pending,success,reason):
    p={'schema_version':1,'command':deepcopy(pending['command']),'request_sha256':proof.digest(pending['command']),
       'rearmed':success,'origin':deepcopy(pending['origin']) if success else None,
       'samples':deepcopy(pending['samples']) if success else [],
       'new_context':deepcopy(pending['new_context']) if success else None,
       'new_generation':pending['new_generation'] if success else None,'no_task_resume':True,'no_native_mutation':True}
    dog.capability_complete(pending['id'],'succeeded' if success else 'failed',reason,new_life_acknowledgment=p)
    if getattr(dog,'_new_life_ack_pending',None) is pending:dog._new_life_ack_pending=None

def submit(dog,request_id,command):
    proof.command(command);now=time.time();accepted=dog.clock()
    p={'id':request_id,'command':deepcopy(command),'origin':deepcopy(getattr(dog,'_new_life_ack_origin',None)),
       'accepted':accepted,'deadline':accepted+min(5,max(0,command['expires_at']-now)),
       'samples':[],'last_sample':None,'new_context':None,'new_generation':None}
    info=status(dog)
    if (not info['eligible'] or info['death_ref']!=command['death_ref']
            or command['expected_defense_epoch']!=dog.defense_epoch or getattr(dog,'_new_life_ack_pending',None) is not None
            or not 0<=now-command['created_at']<5 or now>=command['expires_at']):
        finish(dog,p,False,'new_life_ack_not_eligible');return True
    dog._new_life_ack_pending=p;dog.next_observe=0
    return True

def tick(dog):
    from capability_ownership import safe_policy,context_of,integrated_server_instance_of
    p=getattr(dog,'_new_life_ack_pending',None)
    if p is None:return
    o=p['origin'];sample=getattr(dog,'_new_life_ack_sample',None)
    def current(now,wall_now):
        return (getattr(dog,'_new_life_ack_pending',None) is p and clear_owners(dog) and not dog.armed
            and dog.reason==proof.REASON and dog.defense_epoch==p['command']['expected_defense_epoch']
            and dog.session_id==o['watchdog_session'] and proof.exact(getattr(dog,'_new_life_ack_origin',None),o)
            and now<p['deadline'] and wall_now<p['command']['expires_at'])
    now=dog.clock();wall_now=time.time()
    if not current(now,wall_now):finish(dog,p,False,'new_life_ack_scope_changed_or_expired');return
    if sample is None or sample['request_id']==p['last_sample'] or sample['started']<=p['accepted']:return
    p['last_sample']=sample['request_id'];value=dog.latest;state=value.get('state',{});context=context_of(state)
    generation=proof.generation(state.get('player'))
    if not candidate(dog,o):finish(dog,p,False,'new_life_ack_observation_identity_changed');return
    if p['new_context'] is not None and (not proof.exact(context,p['new_context']) or generation!=p['new_generation']):
        finish(dog,p,False,'new_life_ack_new_instance_changed');return
    tick_value=state.get('world',{}).get('game_time')
    if (not neutral(value) or state.get('screen_open') is not False or type(tick_value) is not int or tick_value<0
            or not 0<=now-sample['received']<=.8):
        p['samples']=[];return
    if p['new_context'] is None:
        p['new_context']=deepcopy(context);p['new_generation']=generation
    if not proof.exact(context,p['new_context']) or generation!=p['new_generation']:
        finish(dog,p,False,'new_life_ack_new_instance_changed');return
    lower=p['samples'][-1]['tick'] if p['samples'] else (o['death_tick'] if context['world_generation']==o['context']['world_generation'] else -1)
    if (tick_value<=lower or sample['request_id']==o['death_request_id']
            or any(v['request_id']==sample['request_id'] for v in p['samples'])):return
    p['samples'].append({'request_id':sample['request_id'],'tick':tick_value})
    if len(p['samples'])<2:return
    def final_binding():
        return proof.encode({'origin':p['origin'],'command':p['command'],'samples':p['samples'],
            'accepted':p['accepted'],'deadline':p['deadline'],'new_context':p['new_context'],'new_generation':p['new_generation'],
            'sample':{k:sample[k] for k in ('request_id','resident_session','bridge_identity','started','received')},
            'game_time':value['state']['world'].get('game_time')})
    frozen_binding=final_binding()
    try:
        resident=dog.q.session()
        if (resident.get('session_id')!=o['resident_session'] or not proof.exact(resident.get('bridge_identity'),o['bridge_identity'])
                or resident.get('state')!='ready' or resident.get('active_request_id') is not None or type(resident.get('pending')) is not int or resident['pending']!=0
                or resident.get('terrain_acquisition_unknown') is not None
                or not safe_policy(resident.get('resident_policy')) or not no_pending_commands(dog,p['id'])):
            finish(dog,p,False,'new_life_ack_final_idle_unconfirmed');return
        # Read both original clocks before the final pure owner/frame fence.
        now=dog.clock();wall_now=time.time()
        if (final_binding()!=frozen_binding or not current(now,wall_now) or dog.latest is not value
                or getattr(dog,'_new_life_ack_sample',None) is not sample or not 0<=now-sample['received']<=.8
                or not candidate(dog,o) or not proof.exact(context_of(value['state']),p['new_context'])
                or proof.generation(value['state'].get('player'))!=p['new_generation']
                or value['state'].get('screen_open') is not False or not neutral(value)):
            finish(dog,p,False,'new_life_ack_final_scope_changed');return
        dog.defense_epoch+=1;dog.armed=True;dog.phase='watching';dog.reason=proof.SUCCESS
        dog._new_life_ack_origin=None
        finish(dog,p,True,dog.reason)
    except (ValueError,OSError,KeyError,TypeError):
        finish(dog,p,False,'new_life_ack_final_read_unconfirmed')
