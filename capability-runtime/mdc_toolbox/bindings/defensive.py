"""Explicit public nonoffensive native combat modes, separately negotiated."""
from copy import deepcopy
from mdc_skills import defensive_combat,threats
from mdc_toolbox.contracts import ToolboxError,obj,integer,validate_schema
from .tactical import UUID,default,number,definition

_SCHEMAS={
    'defend_local':obj({'target_uuid':UUID,'window_ms':default(integer(300,2500),1000)},('target_uuid',)),
    'evade_local':obj({'target_uuid':UUID,'window_ms':default(integer(300,2500),2500),
        'max_distance':default(number(1,4),4),'minimum_separation_gain':default(number(.1,2),.5)},('target_uuid',))}

def definitions():
    result=[]
    for name,schema in _SCHEMAS.items():
        mode='shield_only' if name=='defend_local' else 'immediate_evade'
        value=definition(name,schema,group='combat_threats',level='local_controller',profile='entities',
            sources=(defensive_combat,),actions=('combat_entity',),
            description='One bounded native '+('shield-only window' if name=='defend_local' else 'immediate dry retreat')+' against an exact observed supported threat; no attack.',
            bounds={'native_timeout_ms':3000,'window_ms':[300,2500],'max_observed_travel':0 if mode=='shield_only' else 4,
                'native_attack_dispatches':0,'shared_budget':'original_job_ledger'})
        value.update(adapter_status='scoped_native',public_support='negotiated_profile_required')
        value['native_features']+=['scoped-native-preflight/1','profile:'+defensive_combat.PROFILE]
        value['combat_coverage']={'target_types':sorted(threats.NATIVE_COMBAT_TYPES),'modes':[mode],
            'dimension_policy':'same_bound_private_singleplayer_dimension_dry_loaded_geometry',
            'offensive_effects_allowed':False,'campaign_targets_supported':[],
            'unsupported_campaign_targets':['minecraft:blaze','minecraft:enderman','minecraft:ender_dragon','minecraft:wither','minecraft:wither_skeleton'],
            'projectile_prediction_supported':False}
        value['known_limits']=[line for line in value['known_limits'] if not line.startswith(('Only engage','Engage requires','Existing guarded legacy skill'))]+[
            'Explicit six-target scope only. No acquisition, retargeting or original-task resume.',
            'Observed shield/separation completion leaves risk_remaining; input release is separate from physical safety.',
            'Finite positive health may admit these nonoffensive modes below attack reserve; no selected weapon is needed.',
            'No directional projectile forecast or general Nether/End/Wither combat coverage.',
            'Observed travel cap does not cancel external velocity or prove a physically safe stop.']
        result.append(value)
    return result

def invoke(capability,runtime,arguments,control):
    if capability not in _SCHEMAS:raise ToolboxError('capability_unavailable','Unknown defensive mode')
    validate_schema(arguments,_SCHEMAS[capability]);control.checkpoint()
    result=getattr(defensive_combat,capability)(runtime,**deepcopy(arguments))
    control.emit('defensive_episode_observed',{'capability':capability,'status':result.status,'reason':result.reason,
        'request_ids':list(result.request_ids),'offensive_effects_allowed':False,'risk_remaining':True})
    return result
