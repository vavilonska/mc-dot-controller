"""Pure bounded post-readback. Never settles a protocol, mutates a ledger or retries."""
import math
from .legacy import Refused,PROFILE
from .geometry import latest_valid,primed_valid,observation_geometry

def assess_target(record,obs):
    q=record['request']
    if q['profile']!=PROFILE or q['kind'] not in ('break_block','place_block'):raise Refused('v5 original break/place required')
    latest_valid(obs);hazard=primed_valid(obs)
    if any(obs.get(k)!=q[k] for k in ('session','world_generation','player_uuid')) or obs.get('bound_owner_id')!=q['owner_id']:raise Refused('post observation original native context mismatch')
    original=record.get('observation')
    if not isinstance(original,dict) or type(obs.get('client_tick')) is not int or obs['client_tick']<=original['client_tick']:raise Refused('post target requires later native frame')
    w=obs.get('latest_target_witness')
    if not isinstance(w,dict) or w['action_id']!=q['id'] or any(w[k]!=q[k] for k in 'xyz'):raise Refused('post witness must name original action and target')
    a,_=observation_geometry(original);b,_=observation_geometry(obs);target=tuple(q[k] for k in 'xyz')
    changes=[list(k) for k in sorted(set(a)&set(b)) if k!=target and any(a[k][f]!=b[k][f] for f in ('loaded','id','fluid','collision','collision_boxes'))]
    expected='minecraft:air' if q['kind']=='break_block' else 'minecraft:andesite'
    match=w['loaded'] and w['complete'] and w['id']==expected and w['fluid']=='minecraft:empty'
    clear=hazard['complete'] and not hazard['overflow'] and hazard['count']==0
    terminal=record.get('terminal_native') or {}
    known=record['state']=='CLOSED' and terminal.get('protocol_terminal') is True and terminal.get('release_proven') is True and terminal.get('applied_calls',0)>0
    return dict(protocol_known_released=known,target_observed_expected=match,current_local_primed_clear=clear,changed_other_overlap_cells=changes,qualification=known and match and clear and not changes,physical_settlement='not_observed',scope='current bounded target plus overlap terrain only; no future or global explosion guarantee')
