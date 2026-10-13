"""One existing-owner completed-capture publisher; readers never trigger game I/O."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re

from .adapters import resident_observation
from .schema import Context, canonical, identifier, integer, number, point, require
from .snapshots import Acquisition

SUPPORT = frozenset({'minecraft:stone', 'minecraft:cobblestone', 'minecraft:dirt', 'minecraft:grass_block'})


@dataclass(frozen=True)
class CaptureTicket:
    source_id: str
    started_mono: float
    owner_session: str
    defense_epoch: int
    resident_session: str


def narrow_terrain(raw):
    """Reuse resident's strict terrain parser, further narrowed to four full-cube floors/air."""
    from navigation_controller.terrain import Cell
    require(type(raw) is dict and raw.get('complete') is True
            and type(raw.get('cells')) is list and 1 <= len(raw['cells']) <= 256, 'step_terrain_incomplete')
    # This opt-in owner requests exactly radius1/vertical2. WorldCache's
    # generic export may omit unloaded cells; never turn that subset into a
    # complete planning observation or replace its original sample/time.
    require(type(raw.get('radius')) is int and raw['radius'] == 1
            and type(raw.get('vertical')) is int and raw['vertical'] == 2,
            'step_terrain_extent')
    origin = raw.get('origin')
    require(type(origin) is dict and set(origin) == {'x', 'y', 'z'}, 'step_terrain_origin')
    ox, oy, oz = (integer(origin[k], -30_000_000, 30_000_000) for k in ('x', 'y', 'z'))
    expected = {(x, y, z) for x in range(ox-1, ox+2)
                for y in range(oy-2, oy+3) for z in range(oz-1, oz+2)}
    out, seen = [], set()
    for c in raw['cells']:
        require(type(c) is dict, 'step_terrain_invalid')
        parsed = Cell.parse(c)
        pos = (parsed.position.x, parsed.position.y, parsed.position.z) if hasattr(parsed, 'position') else (parsed.pos.x, parsed.pos.y, parsed.pos.z)
        require(pos not in seen, 'step_duplicate_cell'); seen.add(pos)
        clear = parsed.clear and c.get('id') == 'minecraft:air'
        support = parsed.support and c.get('id') in SUPPORT
        certain = clear or support
        out.append(dict(zip(('x', 'y', 'z'), pos), loaded=certain, block_id=c.get('id'),
                        passable=clear, full_support=support, hazard=False if certain else None,
                        fluid=False if certain else None))
    require(seen == expected and len(out) == 45, 'step_terrain_incomplete')
    return {'cells': out, 'complete': all(c['loaded'] for c in out)}


def step_evidence(state):
    e, world, player, action = state.get('coordination_step'), state['world'], state['player'], state['client_action']
    require(type(e) is dict and type(e.get('schema_version')) is int and e['schema_version'] == 1
            and e.get('contract') == 'controlled_single_step_v1'
            and e.get('singleplayer') is True and e.get('entity_scope') == 'loaded_client_aabb8_excluding_self'
            and type(e.get('radius')) is int and e['radius'] == 8, 'native_step_contract_required')
    require(e.get('world_generation') == world.get('world_generation')
            and e.get('player_uuid') == player.get('uuid')
            and e.get('action_session') == action.get('action_session')
            and e.get('source_tick') == world.get('game_time'), 'native_step_context_changed')
    integer(e.get('source_tick'), 0, 2**53-1); integer(e.get('entity_count'), 0, 2**31-1)
    nano = e.get('source_nano')
    require(type(nano) is str and re.fullmatch(r'-?(0|[1-9][0-9]{0,18})', nano) is not None
            and -(2**63) <= int(nano) <= 2**63-1, 'native_sample_clock_invalid')
    nearby = state.get('nearby', {})
    clear = (e['entity_count'] == 0 and nearby.get('truncated') is False
             and type(nearby.get('radius')) in (int, float) and nearby['radius'] >= 8
             and type(nearby.get('total')) is int and nearby['total'] == 0
             and type(nearby.get('returned')) is int and nearby['returned'] == 0
             and nearby.get('entities') == [])
    return deepcopy(e), clear


class CompletedObservationPublisher:
    """begin is before send; complete reuses resident's original same-host intervals.

    No file timestamp, read time, import time or latest outer status can rejuvenate
    a sample. Raw completed requests are consumed once. Source-native nano is
    echoed unchanged and checked only in that same JVM, never against Python time.
    """
    def __init__(self, store, owner_bridge):
        self.store, self.owner = store, owner_bridge
        self._tickets, self._completed, self._samples = {}, set(), {}

    def begin(self, source_id):
        self.owner.assert_thread(); identifier(source_id)
        require(source_id not in self._tickets and source_id not in self._completed, 'capture_id_already_used')
        require(len(self._tickets) + len(self._completed) < 4096, 'capture_identity_capacity')
        fence = self.owner.capture_fence()
        ticket = CaptureTicket(source_id, self.store.clock(), fence['owner_session'], fence['defense_epoch'], fence['resident_session'])
        self._tickets[source_id] = ticket
        return ticket

    def complete(self, ticket, result, *, ttl_ms=800):
        self.owner.assert_thread()
        require(type(ticket) is CaptureTicket and self._tickets.get(ticket.source_id) is ticket, 'original_capture_ticket_required')
        # Consume even malformed completions; a corrected replay cannot mint freshness.
        del self._tickets[ticket.source_id]; self._completed.add(ticket.source_id)
        integer(ttl_ms, 50, 800)
        require(type(result) is dict and result.get('request_id') == ticket.source_id
                and result.get('session_id') == ticket.resident_session, 'capture_result_identity_changed')
        self.owner.ready(new_request=True, capture_id=ticket.source_id)
        require(all(result.get(key, False) is False for key in ('unknown_outcome', 'uncertain', 'post_uncertain')),
                'capture_transport_uncertainty')
        raw = result.get('result', {})
        if type(raw) is not dict or not self.owner.valid_policy(raw.get('resident_policy')):
            self.owner.interrupt('capture_resident_policy_unconfirmed')
            require(False, 'capture_resident_policy_unconfirmed')
        require(raw['resident_policy']['requires_handoff'] is False
                and raw['resident_policy']['input_release_unconfirmed'] is False,
                'capture_resident_policy_blocks_use')
        state = raw.get('state', {})
        require(type(state) is dict and type(state.get('client_action')) is dict, 'native_state_action_context_required')
        normalized = deepcopy(result); normalized['result']['action'] = deepcopy(state['client_action'])
        data = resident_observation(normalized)
        world, player, action = state['world'], state['player'], state['client_action']
        guard, status = world.get('navigation_guard'), raw.get('status', {})
        require(type(guard) is dict and type(guard.get('schema_version')) is int and guard['schema_version'] == 1, 'navigation_guard_required')
        integer(guard.get('epoch'), 0, 2**53-1); integer(guard.get('stable_ticks'), 0, 3)
        require(type(guard.get('rebind_ready')) is bool and guard['rebind_ready'] == (guard['stable_ticks'] == 3)
                and type(guard.get('fresh_binding_required')) is bool, 'navigation_guard_invalid')
        integer(world.get('game_time'), 0, 2**53-1)
        identifier(status.get('run_id')); integer(status.get('process_id'), 1, 2**53-1)
        require(type(status.get('coordination_step_protocol')) is int and status['coordination_step_protocol'] == 1,
                'native_step_contract_required')
        require(action.get('action_session') == status.get('client_action', {}).get('action_session'), 'observation_lifecycle_changed')
        evidence, clear = step_evidence(state)
        capture = raw.get('coordination_capture', {})
        now = self.store.clock()
        started = number(capture.get('started_mono'), ticket.started_mono, now)
        finished = number(capture.get('finished_mono'), started, now)
        require(self.owner.capture_fence(capture_id=ticket.source_id) == {'owner_session': ticket.owner_session,
                'defense_epoch': ticket.defense_epoch, 'resident_session': ticket.resident_session}, 'capture_owner_changed')
        source_id = hashlib.sha256((ticket.source_id + ':state').encode()).hexdigest()
        private = dict(owner_session=ticket.owner_session, defense_epoch=ticket.defense_epoch,
                       resident_session=ticket.resident_session, run_id=status['run_id'], process_id=status['process_id'],
                       action_session=data['context'].action_session, world_generation=data['context'].world_generation,
                       player_uuid=data['context'].player_id, dimension=data['context'].dimension,
                       navigation_epoch=guard['epoch'], origin=point({k: player.get(k) for k in ('x', 'y', 'z')}),
                       source_id=source_id, source_tick=world['game_time'], source_nano=evidence['source_nano'],
                       captured_mono=started, expires_mono=started+ttl_ms/1000,
                       rebind_ready=guard['rebind_ready'], native_status=action.get('status'), step_clear=clear,
                       terrain_source_id=hashlib.sha256((ticket.source_id+':terrain').encode()).hexdigest() if 'terrain' in raw else None)
        acquisition = Acquisition(self.store.epoch, started, finished, data['source_time_ms'], data['source_tick'], data['source_clock'])
        sections = {**data['sections'], 'entities': {'entities': [], 'truncated': not clear}}
        with self.store._lock:
            self.store.publish(data['context'], source_id, sections, acquisition, ttl_ms)
            if 'terrain' in raw:
                terrain = raw['terrain']
                require(terrain.get('world_generation') == data['context'].world_generation, 'terrain_world_changed')
                tstart = number(terrain.get('capture_started_mono'), ticket.started_mono, started)
                tend = number(terrain.get('capture_finished_mono'), finished, now)
                tacq = Acquisition(self.store.epoch, tstart, tend, data['source_time_ms'],
                                   integer(terrain.get('source_tick'), 0, world['game_time']), data['source_clock'])
                self.store.publish(data['context'], hashlib.sha256((ticket.source_id+':terrain').encode()).hexdigest(),
                                   {'terrain': narrow_terrain(terrain)}, tacq, 3000)
            snapshot = self.store.read()
        sample = snapshot['sections']['player']
        if 'terrain' in raw:
            # The store deliberately pins identical capture intervals across sections.
            private['terrain_source_id'] = snapshot['sections']['terrain']['source_id']
        require(sample['source_id'] == source_id, 'capture_did_not_advance')
        self._samples[sample['sample_id']] = (private, acquisition)
        return snapshot

    def binding(self, snapshot):
        sample = snapshot.get('sections', {}).get('player', {})
        require(sample.get('freshness') == 'fresh' and sample.get('source_time_clock') == 'resident_result_finished_wall', 'live_capture_required')
        stored = self._samples.get(sample.get('sample_id'))
        require(stored is not None and stored[0]['source_id'] == sample.get('source_id'), 'unknown_live_capture')
        private, acquisition = stored
        require(self.store.clock() < private['expires_mono'], 'original_capture_expired')
        require(private['rebind_ready'] is True and private['native_status'] != 'running', 'navigation_not_ready')
        require(private['step_clear'] is True, 'step_entity_clearance_missing')
        require(snapshot['sections'].get('entities', {}).get('source_id') == private['source_id'], 'entities_capture_changed')
        require(private['terrain_source_id'] is not None and snapshot['sections'].get('terrain', {}).get('source_id') == private['terrain_source_id'],
                'fresh_same_scan_terrain_required')
        return deepcopy(private), acquisition
