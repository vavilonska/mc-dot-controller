"""Typed current survival facts, single stage intent, and unchanged navigation geometry."""
import math
from .legacy import PROFILE,Refused,legacy
from .schema import finite,integer
from interaction_controller.policy import context
from interaction2_controller.policy import hotbar
from navigation4_controller import policy as navigation_policy
from navigation4_controller.geometry import box_values
from maintenance5_controller.geometry import primed_valid
SURVIVAL_KEYS={'complete','food_level','saturation','is_using_item','used_hand','use_remaining_ticks','hurt_time','entity_reach','attack_strength','entity_hit'}
HIT_KEYS={'entity_id','uuid','type','provider_class','alive','health','bbox','point'}
BLAZE_CLASS='net.minecraft.world.entity.monster.Blaze'
def survival_valid(obs):
 s=obs.get('survival')
 if not isinstance(s,dict)or set(s)!=SURVIVAL_KEYS or type(s['complete'])is not bool:raise Refused('closed survival facts required')
 if not s['complete']:
  if any(s[k]is not None for k in SURVIVAL_KEYS-{'complete'})or obs['ready']is not False:raise Refused('incomplete survival facts must be explicit and unready')
  return s
 if obs['world_generation']is None:raise Refused('no-world survival facts cannot be complete')
 if not integer(s['food_level'],0,20)or not finite(s['saturation'],0,20)or type(s['is_using_item'])is not bool or not integer(s['use_remaining_ticks'],-2147483648,2147483647)or not integer(s['hurt_time'],0,2147483647)or not finite(s['entity_reach'],0,64)or not finite(s['attack_strength'],0,1):raise Refused('bounded survival scalar facts required')
 if (s['used_hand']not in('MAIN_HAND','OFF_HAND')if s['is_using_item']else s['used_hand']is not None):raise Refused('current use hand mismatch')
 hit=s['entity_hit']
 if hit is not None:
  if not isinstance(hit,dict)or set(hit)!=HIT_KEYS or not integer(hit['entity_id'],-2147483648,2147483647)or hit['type']!='minecraft:blaze'or hit['provider_class']!=BLAZE_CLASS or type(hit['alive'])is not bool or not finite(hit['health'],0,float('inf')):raise Refused('closed eligible exact Blaze witness required')
  legacy.uuid(hit['uuid']);box_values(hit['bbox']);point=hit['point']
  if not isinstance(point,dict)or set(point)!={'x','y','z'}or any(not finite(point[k],-3e7,3e7)for k in 'xyz'):raise Refused('finite current ray point required')
 return s

def selected_stack(obs,slot,expected):
 slots=hotbar(obs);entry=slots.get(slot);item='minecraft:bread'if slot==1 else 'minecraft:iron_axe'if slot==8 else None
 if item is None or entry['item_id']!=item or entry['count']<1 or entry['stack_fingerprint']!=expected:raise Refused('exact current approved full stack required')
 if slot==8 and (entry['count']!=1 or entry['max_damage']<=0 or entry['damage']>=entry['max_damage']):raise Refused('usable exact iron axe required')
 return entry

def gate(obs,req,owner,history,plan):
 context(obs,req,owner);plan.bind(obs);stage=plan.permits(req);facts=survival_valid(obs)
 if not facts['complete']:raise Refused('complete current survival facts required')
 # No hidden HP20, hurt==0, no-fire or empty-enemy invariants for survival actions.
 same=[r for r in history.values()if r['request'].get('profile')in(PROFILE,'recovery_maintenance_v5')and all(r['request'].get(k)==req[k]for k in('session','world_generation','player_uuid'))]
 if 'target'in stage:
  hazard=primed_valid(obs)
  if not hazard['complete']or hazard['overflow']or hazard['count']!=0:raise Refused('navigation preserves current primed TNT policy')
  if req['kind']=='move'and req['jump_first']and any(r['request'].get('kind')=='move'and r['request'].get('jump_first')is True and r['request'].get('stage_id')==req['stage_id']for r in same):raise Refused('same context jump stage already consumed across PLANs')
  mapped={str(i):{'request':dict(r['request'],profile=navigation_policy.PROFILE,plan_sha256=plan.sha256)}for i,r in enumerate(same)}
  return navigation_policy.gate(obs,req,owner,mapped,plan)
 used=[r for r in same if r['request'].get('stage_id')==req['stage_id']and r['request'].get('kind')==req['kind']]
 if len(used)>=stage['max_intents']:raise Refused('one declared stage intent already consumed across PLANs')
 if facts['is_using_item']:raise Refused('existing use lifecycle cannot be adopted or replaced')
 kind=req['kind']
 if kind=='select_hotbar':selected_stack(obs,req['slot'],req['stack_fingerprint'])
 else:
  slot=8 if kind=='attack_blaze'else 1
  if obs['selected_slot']!=slot:raise Refused('exact action slot must already be selected')
  selected_stack(obs,slot,req['stack_fingerprint'])
  if kind=='attack_blaze':
   hit=facts['entity_hit']
   if not isinstance(hit,dict)or not hit['alive']or hit['health']<=0 or facts['attack_strength']<1.0 or any(hit[key]!=req[field]for key,field in(('entity_id','target_entity_id'),('uuid','target_uuid'),('type','target_type'))):raise Refused('current exact eligible Blaze and cooldown required')
   # Native immediately rechecks the actual combined ray/reach. The target is not
   # required to keep its old bbox stationary for the observation-ticket lifetime.
  elif facts['food_level']>=20:raise Refused('current hunger required; never wait for hunger')
 return dict(plan_sha256=plan.sha256,stage_id=stage['id'],gameplay_risk='ordinary_damage_interruption_and_unsuccessful_single_attempt',physical_settlement='not_observed',outcome='not_assessed')
