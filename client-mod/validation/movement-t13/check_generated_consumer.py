"""Narrow generated real witness/codec to unchanged real Python consumer; no external action."""
from pathlib import Path
import sys,json,copy,socket,subprocess,importlib.util
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
S=ROOT.parents[2]
# Established seven-root bootstrap. No discovery of additional test suites.
ROOTS=['resident-controller','capability-runtime','defense-watchdog','building-controller','navigation-controller','navigation-cursor','external-controller']
sys.path[:0]=[str(S/p) for p in ROOTS]
def forbidden(*a,**k):raise AssertionError('offline_packet_external_action_forbidden')
with patch.object(socket,'create_connection',forbidden),patch.object(socket.socket,'connect',forbidden),patch.object(socket.socket,'connect_ex',forbidden),patch.object(socket.socket,'bind',forbidden),patch.object(socket.socket,'listen',forbidden),patch.object(subprocess,'Popen',forbidden):
 from resident_controller.capability_snapshot import validate_snapshot,validate_scoped_witness,exact
 from resident_controller.movement_wire import load_strict
 OUT=Path(sys.argv[1]);checks=[]
 def check(condition,label):
  if not condition:raise AssertionError(label)
  checks.append(label)
 def rejected(action,label):
  try:action()
  except (ValueError,AssertionError,KeyError):checks.append(label);return
  raise AssertionError('expected refusal: '+label)
 original=load_strict((OUT/'generated-intent.json').read_bytes());request=load_strict((OUT/'generated-request.json').read_bytes())
 raw=(OUT/'generated-coherent.json').read_bytes();bundle=load_strict(raw);saved=copy.deepcopy(bundle);decoded=validate_snapshot(bundle,8)
 witness=validate_scoped_witness(decoded['action'],request,original['action_id'],original)
 standalone=load_strict((OUT/'generated-standalone.json').read_bytes());check(exact(validate_scoped_witness(standalone,request,original['action_id'],original),witness),'standalone and complete generated reply share exact real admission witness')
 check(exact(bundle,saved),'real consumer leaves generated raw object unchanged')
 terminal=decoded['action']['result']['scoped_movement']
 for sibling in [decoded['status']['client_action'],decoded['state']['client_action']]:check(exact(sibling['result']['scoped_movement'],terminal),'complete reply sibling terminal preserved')
 check(witness['source_tick']==195867 and witness['facts']['movement']['entity_guard']['source_tick']==195867 and witness['facts']['movement']['entity_guard']['remaining_projection_ticks']==160,'admission world tick/horizon retain original meaning')
 check(terminal['last_entity_check_tick']==195866 and terminal['last_entity_check_action_tick']==1,'terminal distinguishes backward world tick and forward action age')
 driver_path=ROOT/'movement_checks.py'
 spec=importlib.util.spec_from_file_location('accepted_action_tick_driver',driver_path);driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
 def require_terminal(t,native_ticks=1):return driver.observed_entity_terminal_valid(witness,t,native_ticks=native_ticks)
 require_terminal(terminal);checks.append('actual generated terminal passes accepted detached real predicate')
 for key in ['timing_contract','last_entity_check_action_tick']:
  t=copy.deepcopy(terminal);del t[key];rejected(lambda t=t:require_terminal(t),'real predicate rejects missing '+key)
 for v in [None,True,1,'world-time-v1']:
  t=copy.deepcopy(terminal);t['timing_contract']=v;rejected(lambda t=t:require_terminal(t),'real predicate rejects malformed timing marker '+repr(v))
 for v in [None,True,'1',1.0,-1,0,2,160,2147483647,195866]:
  t=copy.deepcopy(terminal);t['last_entity_check_action_tick']=v;rejected(lambda t=t:require_terminal(t),'real predicate rejects malformed or unequal action age '+repr(v))
 for v in [None,True,'1',1.0,-1,0,2,160,2147483647]:rejected(lambda v=v:require_terminal(terminal,v),'real predicate rejects native tick type/range/equality '+repr(v))
 for world_tick in [195866,196027,195871]:
  t=copy.deepcopy(terminal);t['last_entity_check_tick']=world_tick;require_terminal(t);checks.append('real predicate allows typed inter-callback world stamp '+str(world_tick))
 for v in [None,True,'195866',-1,2**63]:
  t=copy.deepcopy(terminal);t['last_entity_check_tick']=v;rejected(lambda t=t:require_terminal(t),'real predicate rejects world stamp type/range '+repr(v))
 for v in [str(int(witness['source_nano'])-1),terminal['deadline_nano']]:
  t=copy.deepcopy(terminal);t['last_entity_check_nano']=v;rejected(lambda t=t:require_terminal(t),'real predicate retains original nano bounds '+v)
 def state_for(action):
  old={'x':12.5,'y':64,'z':25.5,'yaw':0,'pitch':0,'velocity':{'x':0,'y':0,'z':0},'on_ground':True,'health':20,'selected_slot':8,'sprinting':False,'using_item':False,'eye_position':{'x':12.5,'y':65.62,'z':25.5},'bounding_box':{'min':{'x':12.2,'y':64,'z':25.2},'max':{'x':12.8,'y':65.8,'z':25.8}}}
  player=copy.deepcopy(old);player['z']-=1;player['eye_position']['z']-=1
  for side in ('min','max'):player['bounding_box'][side]['z']-=1
  menu={'carried':{'empty':True,'count':0}}
  return SimpleNamespace(player=old,state={'menu':menu}),{'player':player,'menu':menu,'held_inputs':{'neutral':True},'client_action':action,'movement_budget':{'status':'unarmed'}}
 success=copy.deepcopy(standalone);success['status']='succeeded';success['reason']='path_reached';before,state=state_for(success);driver.movement_state_valid(before,state);checks.append('synthetic success envelope exercises real unchanged status/goal/release predicate; not live success')
 for status in ['failed','cancelled','running']:
  action=copy.deepcopy(success);action['status']=status;before,state=state_for(action);rejected(lambda before=before,state=state:driver.movement_state_valid(before,state),'real state predicate rejects '+status+' native status')
 # Preserve actual generated cancellation. Synthetic legacy negative replaces private historical receipt.
 check(standalone['status']=='cancelled' and standalone['reason']=='fixture_end' and standalone['ticks']==1,
       'actual generated action remains cancelled/fixture_end/ticks1')
 before,state=state_for(standalone)
 rejected(lambda:driver.movement_state_valid(before,state),'actual generated cancelled action cannot count as successful movement')
 legacy_cancelled=copy.deepcopy(standalone)
 legacy_cancelled['result']['scoped_movement'].pop('timing_contract')
 legacy_cancelled['result']['scoped_movement'].pop('last_entity_check_action_tick')
 before,state=state_for(legacy_cancelled)
 rejected(lambda:driver.movement_state_valid(before,state),'explicit synthetic legacy cancellation rejected by unchanged success/release predicate')
 rejected(lambda:driver.observed_entity_terminal_valid(legacy_cancelled['result']['scoped_native_preflight'],legacy_cancelled['result']['scoped_movement'],native_ticks=legacy_cancelled['ticks']),'explicit synthetic legacy missing action-domain terminal rejected by detached predicate')
 changed=copy.deepcopy(bundle);changed['action']['result']['scoped_native_preflight']['facts']['movement']['entity_guard']['source_tick']-=1
 rejected(lambda:validate_scoped_witness(validate_snapshot(changed,8)['action'],request,original['action_id'],original),'real consumer rejects changed immutable admission frame')
 changed=copy.deepcopy(bundle);changed['status']['client_action']['result']['scoped_movement']['last_entity_check_action_tick']=2
 rejected(lambda:validate_snapshot(changed,8),'real consumer rejects mixed terminal siblings')
 result={'passed':True,'checks':checks,'wire_bytes':len(raw),'scope':'real unchanged consumer validates native-generated complete witness/reply; accepted detached actual driver validates new terminal fields; successful status/pose envelope is explicitly synthetic; actual generated action stays cancelled; legacy cancellation negative is synthetic; historical T12 evidence is retained separately and is not a public test input'}
 (OUT/'consumer-results.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS generated-consumer checks='+str(len(checks)))
