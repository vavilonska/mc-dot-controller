"""Closed diagnostic v1 reader. Client/server samples are never treated as atomic."""
import re
from .strict import Invalid,closed,integer,number

PATH='/control/recovery-diagnostics/v1/events'
PROFILE='recovery_damage_diagnostics_v1'
MAX_RESPONSE=131072
TOP={'schema_version','profile','enabled','boot_id','window_ms','window_started','window_closed','window_start_nanos','query_nanos','server_first','client_first','client_latest','client_total','client_nonzero_count','first_nonzero_tick','client_dropped','client_samples','damage_total','damage_dropped','damage_events','capture_errors'}
NATIVE={'enabled','owner_id','active_id','profile','state','applied_count','next_generation','entry_count','unknown_lock'}
CLIENT={'nano_time','client_tick','player_uuid','health','position','input','native'}
SERVER={'nano_time','server_tick','game_time','player_uuid','health','position'}
DAMAGE={'sequence','nano_time','server_tick','game_time','player_uuid','health_after','position','original_damage','new_damage','blocked_damage','source_key','direct','causing','client_snapshot_nanos','native_snapshot'}


def boolean(v):
    if type(v) is not bool:raise Invalid('boolean required')

def uuid(v):
    if not isinstance(v,str) or not re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',v):raise Invalid('UUID required')

def text(v):
    if not isinstance(v,str) or not 1<=len(v)<=256:raise Invalid('bounded string required')

def nano(v):integer(v,-9223372036854775808)

def pos(v):
    closed(v,{'x','y','z'})
    for n in v.values():number(n)

def native(v):
    closed(v,NATIVE);boolean(v['enabled'])
    for k in ('owner_id','active_id'):
        if v[k] is not None and (not isinstance(v[k],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,128}',v[k])):raise Invalid('bounded native identity required')
    for k in ('profile','state'):
        if v[k] is not None:text(v[k])
    integer(v['applied_count'],0,32);integer(v['next_generation']);integer(v['entry_count'],0,256);boolean(v['unknown_lock'])

def common(v):
    nano(v['nano_time']);uuid(v['player_uuid']);number(v['health'],0,1000000);pos(v['position'])

def client(v):
    closed(v,CLIENT);common(v);integer(v['client_tick'])
    closed(v['input'],{'forward','strafe','jump'});number(v['input']['forward'],-1,1);number(v['input']['strafe'],-1,1);boolean(v['input']['jump']);native(v['native'])

def entity(v):
    if v is None:return
    closed(v,{'type','uuid','x','y','z'});text(v['type']);uuid(v['uuid'])
    for k in ('x','y','z'):number(v[k])

def damage(v):
    closed(v,DAMAGE);integer(v['sequence'],1);nano(v['nano_time']);integer(v['server_tick']);integer(v['game_time']);uuid(v['player_uuid'])
    for k in ('health_after','original_damage','new_damage','blocked_damage'):number(v[k],0,1000000)
    pos(v['position'])
    if v['source_key'] is not None:text(v['source_key'])
    entity(v['direct']);entity(v['causing'])
    if v['client_snapshot_nanos'] is not None:nano(v['client_snapshot_nanos'])
    if v['native_snapshot'] is not None:native(v['native_snapshot'])

def validate(v):
    closed(v,TOP)
    if type(v['schema_version']) is not int or v['schema_version']!=1 or v['profile']!=PROFILE:raise Invalid('diagnostic profile/version mismatch')
    for k in ('enabled','window_started','window_closed'):boolean(v[k])
    uuid(v['boot_id']);nano(v['query_nanos'])
    if type(v['window_ms']) is not int or v['window_ms']!=15000:raise Invalid('native finite15s window required')
    if v['window_start_nanos'] is not None:nano(v['window_start_nanos'])
    if v['window_started']!=(v['window_start_nanos'] is not None):raise Invalid('window identity contradiction')
    if v['window_closed'] and not v['window_started']:raise Invalid('window closed before start')
    if v['window_started'] and v['query_nanos']<v['window_start_nanos']:raise Invalid('native time regressed')
    for k in ('client_total','client_nonzero_count','client_dropped','damage_total','damage_dropped','capture_errors'):integer(v[k])
    if v['first_nonzero_tick'] is not None:integer(v['first_nonzero_tick'])
    if v['client_nonzero_count']>v['client_total'] or (v['client_nonzero_count']>0)!=(v['first_nonzero_tick'] is not None):raise Invalid('nonzero counter contradiction')
    if v['server_first'] is not None:
        closed(v['server_first'],SERVER);common(v['server_first']);integer(v['server_first']['server_tick']);integer(v['server_first']['game_time'])
    for k in ('client_first','client_latest'):
        if v[k] is not None:client(v[k])
    for key,reader,total in (('client_samples',client,'client_total'),('damage_events',damage,'damage_total')):
        if not isinstance(v[key],list) or len(v[key])>32 or len(v[key])>v[total]:raise Invalid('bounded sample array required')
        for sample in v[key]:reader(sample)
    if v['client_dropped']>v['client_total'] or v['damage_dropped']>v['damage_total']:raise Invalid('dropped counter contradiction')
    if not v['window_started'] and (v['server_first'] is not None or v['client_first'] is not None or v['client_latest'] is not None or v['client_total'] or v['damage_total']):raise Invalid('preworld capture contradiction')
    return v
