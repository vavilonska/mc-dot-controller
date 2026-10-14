"""Fabricated finite wire fixtures, never engine or live pickup evidence."""
from copy import deepcopy
from .movement_fixture import movement_fixture
from .menu_fixture import digest

UUID='12345678-1234-1234-1234-123456789abc'
FP='12345678-1234-1234-1234-123456789def'

def collect_fixture(collecting=True):
    native,scope,aid,intent=movement_fixture()
    profile='collect-local-observed-v1' if collecting else 'movement-flat-observed-v2'
    scope['profile']=profile
    w=native['result']['scoped_native_preflight'];w['profile']=profile
    m=w['facts']['movement'];m['profile']=profile
    for k in ('entity_limit','live_other_entities','entity_scope'):m.pop(k)
    guard={'schema_version':1,'policy':'observed-projection-v1','source':'native-client-loaded-level',
      'scope':'all-client-loaded-enumerated-local-corridor-exclusion','guarantee':'same-callback-current-facts-only',
      'future_dynamics_certified':False,'server_confirmed':False,'entity_limit':1024,'enumerated_count':1,
      'self_count':1,'live_other_count':0,'removed_count':0,'unsupported_count':0,'source_tick':w['source_tick'],
      'source_nano':w['source_nano'],'maximum_action_ticks':160,'remaining_projection_ticks':160,
      'prism':[m['min_x'],m['min_y'],m['min_z'],m['max_x']+1,m['max_y']+1,m['max_z']+1],'rows':[]}
    m['entity_guard']=guard
    if collecting:
        target={'uuid':UUID,'entity_id':7,'item_id':'minecraft:coal','count':3,'item_fingerprint':FP,
                'component_fingerprint':FP,'x':1.5,'y':64.,'z':.5}
        intent['pickup_target']=deepcopy(target);m['pickup_target']={**target,'simple_components':True,'on_ground':True,'resting_envelope':'vanilla-grounded-item-v1'}
        guard.update(enumerated_count=2,live_other_count=1,permitted_pickup_uuid=UUID)
        guard['rows']=[{'id':7,'uuid':UUID,'type':'minecraft:item','class':'net.minecraft.world.entity.item.ItemEntity',
           'removed':False,'position':[1.5,64.,.5],'aabb':[1.375,64.,.375,1.625,64.25,.625],
           'velocity':[0.,0.,0.],'lerp_target':[1.5,64.,.5],'projected_aabb':[1.375,64.,.375,1.625,64.25,.625],
           'verdict':'pickup_target','flags':{'living':False,'alive':True,'dying':False,'passenger':False,
           'has_passengers':False,'leashed':False,'no_physics':False,'on_fire':False,'active_effect_count':0,
           'hurt_time':0,'mob_target_uuid':None}}]
    redigest(native,intent)
    return native,scope,aid,intent

def redigest(native,intent):
    w=native['result']['scoped_native_preflight'];compiled=deepcopy(intent)
    compiled['capability_guard']={'schema_version':1,'source_tick':w['source_tick'],'source_nano':w['source_nano']}
    w.update(submitted_intent_sha256=digest(intent),command_sha256=digest(compiled))
