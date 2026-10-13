"""Strict immutable parsing of the selected read-only producer clock.

No IO, clock generation, defaulting, elapsed-time conversion or action authority.
Raw game-time fields are deliberately absent from this counter's arithmetic.
"""
from dataclasses import dataclass
import re
from uuid import UUID

CONTRACT = 'client-pre-tick-v1'
PROFILE = 'read_only'
MAX_COUNT = 2**53 - 1
CONTEXT_KEYS = ('run_id', 'process_id', 'integrated_server_instance',
                'world_generation', 'dimension', 'player_uuid', 'action_session')
DOMAIN_KEYS = {'contract', 'clock_generation', 'origin_nano', 'context'}

def need(value, reason):
    if not value: raise ValueError('observation_clock_' + reason)

def canonical_uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False

def integer(value, low=0, high=MAX_COUNT):
    return type(value) is int and low <= value <= high

def signed_nano(value):
    return (type(value) is str and re.fullmatch(r'(0|-?[1-9][0-9]{0,18})', value) is not None
            and -(2**63) <= int(value) < 2**63)

def domain(value):
    need(type(value) is dict and set(value) == DOMAIN_KEYS, 'domain_schema')
    need(value['contract'] == CONTRACT and type(value['contract']) is str, 'contract')
    need(canonical_uuid(value['clock_generation']) and signed_nano(value['origin_nano']), 'origin')
    ctx=value['context']
    need(type(ctx) is dict and set(ctx) == set(CONTEXT_KEYS), 'context_schema')
    need(integer(ctx['process_id'], 1), 'process_id')
    need(all(type(ctx[k]) is str and bool(ctx[k]) for k in
             ('run_id', 'integrated_server_instance', 'dimension')), 'context_text')
    need(all(canonical_uuid(ctx[k]) for k in ('world_generation', 'player_uuid', 'action_session')), 'context_uuid')
    return (value['contract'], value['clock_generation'], value['origin_nano'],
            tuple(ctx[k] for k in CONTEXT_KEYS))

@dataclass(frozen=True)
class ClockStamp:
    identity: tuple
    count: int

    @classmethod
    def parse(cls, value):
        need(type(value) is dict and set(value) == DOMAIN_KEYS | {'count'}, 'stamp_schema')
        need(integer(value['count']), 'count')
        return cls(domain({k:v for k,v in value.items() if k != 'count'}), value['count'])

    def as_domain(self):
        contract, generation, nano, context = self.identity
        return dict(contract=contract,clock_generation=generation,origin_nano=nano,
                    context=dict(zip(CONTEXT_KEYS,context)))

    def as_dict(self):
        return dict(self.as_domain(),count=self.count)

    def after(self, earlier):
        need(isinstance(earlier,ClockStamp) and self.identity == earlier.identity, 'domain_changed')
        need(self.count >= earlier.count, 'count_reversed')
        return self.count-earlier.count

def bind(value, status, state=None):
    stamp=ClockStamp.parse(value);ctx=stamp.as_domain()['context']
    world=status.get('world',{});player=status.get('player',{});action=status.get('client_action',{})
    expected={'run_id':status.get('run_id'),'process_id':status.get('process_id'),
              'world_generation':world.get('world_generation'),'dimension':world.get('dimension'),
              'player_uuid':player.get('uuid'),'action_session':action.get('action_session')}
    need(all(type(ctx[k]) is type(v) and ctx[k] == v for k,v in expected.items()), 'snapshot_identity')
    if state is not None:
        need(state.get('world',{}).get('integrated_server_instance') == ctx['integrated_server_instance'], 'server_identity')
    return stamp

def selected_status(status):
    need(type(status) is dict and status.get('observation_clock_profile') == PROFILE, 'status_profile')
    need('observation_clock' in status and 'observation_clock_unavailable' in status, 'status_schema')
    need(type(status.get('observation_clock_seen')) is bool, 'seen_schema')
    value,reason=status['observation_clock'],status['observation_clock_unavailable']
    if value is None:
        need(status['observation_clock_seen'] is False and reason in {'not_in_world','uninitialized'}, 'unavailable_permanent_refusal')
        need((reason == 'not_in_world') is (status.get('in_world') is False), 'unavailable_presence')
        return None
    need(reason is None and status.get('in_world') is True and status['observation_clock_seen'] is True, 'available_status')
    return bind(value,status)

def terrain_clocks(terrain, state, max_ticks=5):
    need(type(terrain) is dict and terrain.get('observation_clock_profile') == PROFILE, 'terrain_profile')
    first,last,response=(ClockStamp.parse(terrain.get(k)) for k in
                        ('first_source_clock','last_source_clock','last_response_clock'))
    final=ClockStamp.parse(state.get('observation_clock'))
    last.after(first);response.after(last);final.after(response)
    need(final.after(first) <= max_ticks and final.after(last) <= max_ticks, 'terrain_stale')
    return first,last,response,final

def reject_legacy(value):
    if isinstance(value,dict):
        need('observation_clock' not in value and 'observation_clock_profile' not in value,
             'read_only_legacy_use_forbidden')
