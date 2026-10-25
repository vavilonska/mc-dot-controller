"""Closed new-profile controller. UNKNOWN evidence is append-only and sticky."""
import base64
import copy
import math
import hashlib
import struct
import time
import os
import stat
import re
from urllib.parse import urlencode
from uuid import UUID, uuid4
from .storage import Ledger, Refused, encode, strict_json
from .transport import MAX_RESPONSE
from .policy import local_gate

PROFILE = 'recovery_short_input_v1'
ROOT = '/control/recovery-short-input/v1/'
START_KEYS = {'schema_version', 'profile', 'id', 'owner_id', 'session', 'world_generation', 'player_uuid', 'owner_generation', 'forward', 'strafe', 'samples', 'jump_first', 'ttl_ms', 'observation_id'}
IDENTITY = ('id', 'owner_id', 'session', 'world_generation', 'player_uuid', 'owner_generation')
OBSERVATION_KEYS = {'schema_version','profile','session','owner_generation','bound_owner_id','unknown_lock','active_id','ready','reason','world_generation','player_uuid','paused','screen_open','alive','pose','velocity','on_ground','health','local_blocks','nearby_living','nearby_truncated','terrain_complete','observation_id','client_tick'}
STATUS_KEYS = {'schema_version', 'profile', *IDENTITY, 'state', 'reason', 'requested_samples', 'applied_samples', 'input_invalidated', 'release_proven', 'settled', 'gameplay_outcome', 'unknown_lock', 'payload_digest', 'protocol_state', 'effect_state', 'release_state', 'settlement_state', 'cancellation_generation', 'protocol_terminal'}


def uuid(value):
    if not isinstance(value, str): raise Refused('invalid UUID binding')
    try:
        if str(UUID(value)) != value: raise Refused('UUID must be canonical')
    except ValueError: raise Refused('invalid UUID binding') from None


def request_valid(req):
    if not isinstance(req, dict) or set(req) != START_KEYS or type(req['schema_version']) is not int or req['schema_version'] != 1 or req['profile'] != PROFILE:
        raise Refused('closed start schema required')
    for key in ('id', 'owner_id', 'session', 'player_uuid', 'observation_id'): uuid(req[key])
    if not isinstance(req['world_generation'], str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', req['world_generation']): raise Refused('invalid world generation')
    if type(req['owner_generation']) is not int or not 1 <= req['owner_generation'] <= 9007199254740991: raise Refused('invalid owner generation')
    for key in ('forward', 'strafe'):
        if type(req[key]) not in (int, float) or not math.isfinite(req[key]) or not -1 <= req[key] <= 1: raise Refused('invalid movement')
    if type(req['samples']) is not int or not 1 <= req['samples'] <= 8 or type(req['jump_first']) is not bool or type(req['ttl_ms']) is not int or not 100 <= req['ttl_ms'] <= 2000:
        raise Refused('invalid finite input bounds')


def payload_digest(req):
    def string(s):
        b=s.encode('ascii')
        return struct.pack('>H',len(b))+b
    raw=b''.join(string(req[k]) for k in ('id','session','owner_id'))
    raw+=struct.pack('>q',req['owner_generation'])
    raw+=b''.join(string(req[k]) for k in ('world_generation','player_uuid'))
    raw+=struct.pack('>ddi?i',float(req['forward']) or 0.0,float(req['strafe']) or 0.0,req['samples'],req['jump_first'],req['ttl_ms'])
    raw+=string(req['observation_id'])
    return hashlib.sha256(raw).hexdigest()


class Controller:
    MAX_ACTIONS = 128
    MAX_EVIDENCE = 64

    def __init__(self, directory, transport):
        self.ledger = Ledger(directory)
        self.transport = transport
        self._last_observation = None
        data = self.ledger.data
        if data['endpoint'] is None:
            data['endpoint'] = transport.endpoint
            self.ledger.save()
        elif data['endpoint'] != transport.endpoint:
            self.close()
            raise Refused('ledger cannot switch endpoint/profile')
        try:
            # The single immutable local owner lives in its own private durable record.
            owner_path = self.ledger.directory / 'owner.json'
            if owner_path.exists():
                fd = os.open(owner_path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    meta = os.fstat(stream.fileno())
                    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) & 0o077 or meta.st_uid != os.getuid(): raise Refused('owner record must be private and user-owned')
                    raw = stream.read(4097)
                if len(raw)>4096: raise Refused('owner record too large')
                owner = strict_json(raw)
                if not isinstance(owner, dict) or set(owner) != {'owner_id'}: raise Refused('invalid local owner')
                self.owner_id = owner['owner_id']
                uuid(self.owner_id)
            else:
                if data['actions']: raise Refused('missing original owner; do not replace')
                self.owner_id = str(uuid4())
                # Reuse the durable atomic writer, with no mutation before owner commit.
                saved_path, saved_data = self.ledger.path, self.ledger.data
                try:
                    self.ledger.path, self.ledger.data = owner_path, {'owner_id': self.owner_id}
                    self.ledger.save()
                finally:
                    self.ledger.path, self.ledger.data = saved_path, saved_data
            for record in data['actions'].values():
                request_valid(record['request'])
                if record['request']['owner_id'] != self.owner_id: raise Refused('original owner record mismatch')
                if record['state'] == 'CLOSED':
                    terminal = record.get('terminal_native')
                    self._validate_receipt(terminal, record['request'])
                    if terminal['state'] != 'SETTLED': raise Refused('missing known terminal original')
        except BaseException:
            self.close()
            raise

    def close(self): self.ledger.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def report(self, action_id=None):
        data = self.ledger.data
        if action_id is not None:
            if action_id not in data['actions']: raise Refused('unknown original ID')
            return copy.deepcopy(data['actions'][action_id])
        return copy.deepcopy(data)

    def _unknown(self, rec, reason):
        if rec['state'] == 'CLOSED':
            rec.setdefault('diagnostic_failures', []).append(reason)
            self.ledger.save()
            return
        rec['state'] = 'UNKNOWN'
        if reason not in rec['unknown_reasons']: rec['unknown_reasons'].append(reason)
        self.ledger.data['unknown_lock'] = True
        self.ledger.save()

    def _room(self, rec, reserved=0):
        if len(rec['evidence']) >= self.MAX_EVIDENCE - reserved: raise Refused('evidence capacity exhausted; preserve ledger')
        # Reserve enough ledger space BEFORE dispatch to retain a maximal raw receipt.
        if len(encode(self.ledger.data)) + MAX_RESPONSE * 2 * (reserved + 1) > self.ledger.MAX_BYTES: raise Refused('ledger capacity exhausted; no dispatch')

    def _exchange(self, rec, kind, method, path, body=None):
        reserve = 2 if kind == 'start' or (kind == 'status' and rec['state'] != 'CLOSED' and not rec['stop_attempted']) else 1 if kind == 'stop' else 0
        self._room(rec, reserve)
        try:
            raw = self.transport.request(method, path, body)
        except Exception:
            self._unknown(rec, kind + '_transport_uncertain')
            return None
        # Preserve exact bounded bytes before parsing, including malformed/error replies.
        rec['evidence'].append({'kind': kind, 'http_status': raw.status, 'complete': raw.complete,
                                'raw_base64': base64.b64encode(raw.body[:MAX_RESPONSE]).decode('ascii')})
        self.ledger.save()
        try:
            if not raw.complete or len(raw.body) > MAX_RESPONSE or not 200 <= raw.status < 300: raise Refused('incomplete or unsuccessful receipt')
            receipt = strict_json(raw.body)
            self._validate_receipt(receipt, rec['request'])
            previous = rec['latest_native']
            if previous is not None and (receipt['applied_samples'] < previous['applied_samples'] or receipt['cancellation_generation'] < previous['cancellation_generation']): raise Refused('native evidence regressed')
        except (Refused, KeyError, TypeError):
            self._unknown(rec, kind + '_receipt_uncertain')
            return None
        rec['latest_native'] = receipt
        if receipt['unknown_lock'] or receipt['state'] == 'UNKNOWN':
            self._unknown(rec, kind + '_native_unknown')
        elif kind != 'stop' and rec['state'] != 'UNKNOWN' and receipt['state'] == 'SETTLED' and receipt['release_proven'] and receipt['settled']:
            rec['state'] = 'CLOSED'
            if rec.get('terminal_native') is None: rec['terminal_native'] = copy.deepcopy(receipt)
            self.ledger.save()
        else:
            self.ledger.save()
        return receipt

    @staticmethod
    def _validate_receipt(r, req):
        if not isinstance(r, dict) or set(r) != STATUS_KEYS or r['schema_version'] != 1 or type(r['schema_version']) is not int or r['profile'] != PROFILE:
            raise Refused('closed native receipt schema mismatch')
        if any(type(r[k]) is not type(req[k]) or r[k] != req[k] for k in IDENTITY): raise Refused('receipt original identity mismatch')
        if r['requested_samples'] != req['samples'] or type(r['requested_samples']) is not int or type(r['applied_samples']) is not int or not 0 <= r['applied_samples'] <= req['samples']: raise Refused('invalid sample receipt')
        if r['state'] == 'QUEUED' and r['applied_samples'] != 0: raise Refused('queued input count contradiction')
        if r['state'] not in ('QUEUED', 'ACTIVE', 'STOPPING', 'SETTLED', 'UNKNOWN') or r['protocol_state'] != r['state']: raise Refused('invalid protocol state')
        if any(type(r[k]) is not bool for k in ('input_invalidated', 'release_proven', 'settled', 'unknown_lock', 'protocol_terminal')): raise Refused('invalid certainty field')
        if r['gameplay_outcome'] != 'not_assessed' or not isinstance(r['reason'], str) or not re.fullmatch('[a-f0-9]{64}', r['payload_digest']): raise Refused('invalid outcome receipt')
        if r['payload_digest'] != payload_digest(req): raise Refused('payload digest mismatch')
        if type(r['cancellation_generation']) is not int or r['cancellation_generation'] < 0: raise Refused('invalid cancellation generation')
        if r['effect_state'] not in ('not_started', 'samples_written', 'unknown') or r['release_state'] not in ('not_needed', 'pending', 'proven', 'unknown') or r['settlement_state'] != 'not_observed': raise Refused('invalid dimensions')
        if r['state'] == 'SETTLED' and (not r['settled'] or not r['protocol_terminal'] or not r['release_proven'] or not r['input_invalidated'] or r['release_state'] not in ('proven','not_needed')): raise Refused('contradictory protocol terminal')
        if r['release_state'] == 'not_needed' and (r['applied_samples'] != 0 or r['effect_state'] not in (('not_started','unknown') if r['state']=='UNKNOWN' else ('not_started',))): raise Refused('contradictory no-input release')
        if r['state'] == 'SETTLED' and r['effect_state'] == 'unknown': raise Refused('terminal effect unknown')
        if r['effect_state'] == 'not_started' and r['applied_samples'] != 0: raise Refused('contradictory effect count')
        if r['effect_state'] == 'samples_written' and r['applied_samples'] == 0: raise Refused('contradictory effect count')
        if r['state'] != 'SETTLED' and (r['settled'] or r['protocol_terminal']): raise Refused('contradictory protocol terminal')

    def start(self, request):
        request_valid(request)
        data = self.ledger.data
        old = data['actions'].get(request['id'])
        if old is not None:
            if old['request'] != request: raise Refused('original ID payload mismatch')
            return self.report(request['id'])  # Never resend a sameID POST, even on known rejection.
        if request['owner_id'] != self.owner_id: raise Refused('cannot adopt a replacement owner')
        if data['unknown_lock'] or any(r['state'] in ('PENDING', 'UNKNOWN') for r in data['actions'].values()): raise Refused('original action locks new dispatch')
        if len(data['actions']) >= self.MAX_ACTIONS: raise Refused('action capacity exhausted')
        observation = self._last_observation
        if observation is None or observation.get('observation_id') != request['observation_id']: raise Refused('original fresh local observation required')
        risk = local_gate(observation, request, self.owner_id)
        rec = {'local_risk': risk, 'observation': observation, 'request': copy.deepcopy(request), 'state': 'PENDING', 'unknown_reasons': [], 'evidence': [], 'latest_native': None, 'terminal_native': None, 'stop_attempted': False}
        self._room(rec, 2)
        data['actions'][request['id']] = rec
        self.ledger.save()  # MUST finish atomic replace + file and directory fsync before POST.
        self._exchange(rec, 'start', 'POST', ROOT + 'start', request)
        return self.report(request['id'])

    def status(self, action_id):
        rec = self.ledger.data['actions'].get(action_id)
        if rec is None: raise Refused('unknown original ID')
        req = rec['request']
        query = {k: req[k] for k in ('id', 'session', 'owner_id', 'owner_generation')}
        self._exchange(rec, 'status', 'GET', ROOT + 'status?' + urlencode(query))
        return self.report(action_id)

    def stop(self, action_id):
        rec = self.ledger.data['actions'].get(action_id)
        if rec is None: raise Refused('unknown original ID')
        if rec['stop_attempted']: return self.report(action_id)
        self._room(rec, 1)
        req = rec['request']
        body = {k: req[k] for k in ('schema_version', 'profile', 'id', 'session', 'owner_id', 'owner_generation')}
        rec['stop_attempted'] = True
        self.ledger.save()  # No retry if stop itself is interrupted or response is lost.
        self._exchange(rec, 'stop', 'POST', ROOT + 'stop', body)
        return self.report(action_id)

    def finish_one_step(self, action_id, *, clock=time.monotonic, sleep=time.sleep):
        """Bounded reads of the original finite action; never repeat gameplay POST.

        Natural native release is preferred. Exact stop is used only when settlement
        cannot be observed within the original TTL plus a bounded reporting margin.
        """
        rec = self.ledger.data['actions'].get(action_id)
        if rec is None: raise Refused('unknown original ID')
        deadline = clock() + rec['request']['ttl_ms'] / 1000 + .5
        while rec['state'] == 'PENDING' and clock() < deadline and len(rec['evidence']) < self.MAX_EVIDENCE - 2:
            try: self.status(action_id)
            except Refused:
                self._unknown(rec, 'bounded_read_capacity_exhausted')
                break
            if rec['state'] == 'PENDING': sleep(.1)
        if rec['state'] == 'PENDING': self._unknown(rec, 'bounded_settlement_not_observed')
        if rec['state'] != 'CLOSED':
            self.stop(action_id)
            self.status(action_id)  # New evidence only; UNKNOWN cannot be erased.
        return self.report(action_id)

    def observe(self):
        raw = self.transport.request('GET', ROOT + 'observe')
        if not raw.complete or len(raw.body) > MAX_RESPONSE or raw.status != 200: raise Refused('observation unavailable')
        obs = strict_json(raw.body)
        if not isinstance(obs, dict) or set(obs) != OBSERVATION_KEYS or type(obs.get('schema_version')) is not int or obs.get('schema_version') != 1 or obs.get('profile') != PROFILE: raise Refused('observation contract mismatch')
        if obs['world_generation'] is None:
            if obs['client_tick'] is not None: raise Refused('no-world native frame must be null')
        elif type(obs['client_tick']) is not int or obs['client_tick'] < 0:
            raise Refused('invalid native client frame')
        self._last_observation = copy.deepcopy(obs)
        return obs
