#!/usr/bin/env python3
"""Serial ordinary break/path batch; one POST per ID, native damage guard, explicit retreat.
No V6, key writer, new native code, world edits, or action replay. Run in desktop namespace.
"""
import argparse
import copy
import datetime
import http.client
import json
import math
from pathlib import Path
import time
import uuid

N = Path('/workspace/scratch/5f333e5a575b/MDC-RECOVERY-LIVE-F1220-20261022')
TOKEN = N / 'polymc-data/instances/MDC-RECOVERY-F1220-20261022/minecraft/config/mineclient-bridge.token'
TERMINAL = {'succeeded', 'failed', 'cancelled'}

class Stop(Exception):
    pass

def identity(s):
    return (s['world']['world_generation'], s['player']['uuid'],
            s['player'].get('generation'), s['client_action']['action_session'])

def pose(s):
    return {k: s['player'][k] for k in ('x', 'y', 'z')}

def danger(s, health=None):
    p = s['player']
    if not p['alive']:
        return 'player_dead'
    for name in ('in_lava', 'on_fire', 'in_water', 'eye_in_water', 'in_powder_snow'):
        if p.get(name):
            return name
    if health is not None and p['health'] < health:
        return 'health_decreased'
    return None

def require_world(s):
    if not s.get('private_singleplayer') or s.get('paused') or s.get('screen_open'):
        raise Stop('private_unpaused_world_required')
    if not s['player']['alive']:
        raise Stop('player_dead')

def validate_plan(value):
    items = value['actions'] if isinstance(value, dict) and 'actions' in value else [value]
    if not isinstance(items, list) or not items:
        raise Stop('nonempty_actions_required')
    for p in items:
        if not isinstance(p, dict) or p.get('action') not in ('break_block', 'follow_path'):
            raise Stop('only_break_block_and_follow_path_supported')
        if any(k == 'action_id' or k == 'capability_guard' or k.startswith('expected_') for k in p):
            raise Stop('identity_and_guard_are_bound_from_fresh_state')
        timeout = p.get('timeout_ms', 15000)
        if type(timeout) is not int or not 50 <= timeout <= 60000:
            raise Stop('native_capability_timeout_range_50_to_60000')
        if p['action'] == 'break_block':
            if set(p.get('target', {})) != {'x', 'y', 'z'} or any(type(v) is not int for v in p['target'].values()):
                raise Stop('integer_target_required')
        else:
            validate_points(p.get('waypoints'))
    return copy.deepcopy(items)

def validate_points(points):
    if not isinstance(points, list) or not points:
        raise Stop('explicit_waypoints_required')
    for p in points:
        if not isinstance(p, dict) or any(type(p.get(k)) not in (int, float) or not math.isfinite(p[k]) for k in ('x', 'y', 'z')):
            raise Stop('finite_waypoint_required')

def validate_retreat(value):
    if value is None:
        return None
    if value.get('known_tunnel') is not True:
        raise Stop('explicit_known_tunnel_retreat_required')
    validate_points(value.get('waypoints'))
    timeout = value.get('timeout_ms', 3000)
    if type(timeout) is not int or not 50 <= timeout <= 60000:
        raise Stop('invalid_retreat_timeout')
    return copy.deepcopy(value)

class Client:
    def __init__(self, out):
        self.out = out
        self.token = TOKEN.read_text().strip()
    def note(self, kind, **data):
        row = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), kind=kind, **data)
        with (self.out / 'events.jsonl').open('a') as f:
            f.write(json.dumps(row, separators=(',', ':')) + '\n')
    def exchange(self, method, path, payload=None):
        self.note('request', method=method, path=path, payload=payload, attempts=1)
        conn = http.client.HTTPConnection('127.0.0.1', 38121, timeout=2 if method == 'GET' else 5)
        try:
            conn.request(method, path, None if payload is None else json.dumps(payload).encode(),
                         {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
            r = conn.getresponse()
            raw = r.read()
            obj = json.loads(raw)
            self.note('response', method=method, path=path, http_status=r.status, body=obj)
            return r.status, obj
        except Exception as e:
            self.note('transport_error', method=method, path=path, error=type(e).__name__,
                      outcome='UNKNOWN_NO_REISSUE' if method == 'POST' else 'READ_FAILED')
            raise
        finally:
            conn.close()
    def state(self):
        code, s = self.exchange('GET', '/control/state?radius=0')
        if code != 200:
            raise Stop('state_unavailable')
        return s

def needed_cells(s, target):
    t = tuple(target[k] for k in ('x', 'y', 'z'))
    out = {t}
    for axis in range(3):
        for d in (-1, 1):
            q = list(t); q[axis] += d; out.add(tuple(q))
    foot = tuple(math.floor(s['player'][k]) for k in ('x', 'y', 'z'))
    out.update((foot, (foot[0], foot[1] + 1, foot[2]), (foot[0], foot[1] - 1, foot[2])))
    return out

def check_cells(cells, needed):
    for p in sorted(needed):
        c = cells.get(p)
        if c is None or c.get('status') != 'loaded' or c.get('known') is not True:
            raise Stop('required_terrain_unknown:' + str(p))
        if c.get('fluid') != 'minecraft:empty' or c.get('fluid_truncated'):
            raise Stop('adjacent_fluid:' + str(p))
        if set(c.get('hazards', [])) & {'lava', 'water', 'contact_damage', 'powder_snow'}:
            raise Stop('adjacent_hazard:' + str(p))

def read_neighbours(c, s, target):
    needed = needed_cells(s, target)
    origin = tuple(math.floor(s['player'][k]) for k in ('x', 'y', 'z'))
    radius = max(max(abs(p[0]-origin[0]), abs(p[2]-origin[2])) for p in needed)
    vertical = max(abs(p[1]-origin[1]) for p in needed)
    if radius > 16 or vertical > 8:
        raise Stop('target_neighbours_outside_existing_terrain_range')
    path = f'/control/terrain?radius={radius}&vertical={vertical}&limit=1024&capability=1'
    cells = {}; cursors = set()
    while True:
        code, obj = c.exchange('GET', path)
        if code != 200 or obj.get('world_generation') != s['world']['world_generation']:
            raise Stop('terrain_unavailable_or_context_changed')
        for row in obj.get('cells', []):
            cells[tuple(row[k] for k in ('x', 'y', 'z'))] = row
        if needed <= cells.keys():
            check_cells(cells, needed)
            return cells
        cursor = obj.get('next_cursor')
        if not cursor or cursor in cursors:
            raise Stop('required_terrain_incomplete')
        cursors.add(cursor)
        time.sleep(max(0, obj.get('retry_after_ms', 100)) / 1000)
        path = '/control/terrain?cursor=' + cursor

def bind_action(spec, s, target_cell=None, guarded=True):
    require_world(s)
    if s['client_action'].get('status') == 'running':
        raise Stop('another_action_running')
    b = copy.deepcopy(spec)
    b.update(action_id=str(uuid.uuid4()), expected_world_generation=s['world']['world_generation'],
             expected_player_uuid=s['player']['uuid'], expected_action_session=s['client_action']['action_session'],
             expected_navigation_epoch=s['world']['navigation_guard']['epoch'], expected_origin=pose(s))
    if guarded:
        guard = s.get('capability_guard_monotonic')
        if not isinstance(guard, dict) or guard.get('schema_version') != 2:
            raise Stop('native_monotonic_guard_unavailable_no_legacy_fallback')
        b['capability_guard'] = copy.deepcopy(guard)
        b['expected_dimension'] = s['world']['dimension']
        b['expected_hotbar_slot'] = s['player']['selected_slot']
        slot = b.get('hotbar_slot', s['player']['selected_slot'])
        if slot == -1:
            slot = s['player']['selected_slot']
        item = next((i for i in s['player']['inventory'] if i['slot'] == slot), None)
        if not item or not item.get('item_fingerprint'):
            raise Stop('fresh_held_item_fingerprint_missing')
        b['expected_held_item'] = copy.deepcopy(item)
        if b['action'] == 'break_block':
            if not target_cell or not target_cell.get('id'):
                raise Stop('fresh_target_id_missing')
            b['expected_block_id'] = target_cell['id']
    return b

def terminal_known(obj, b):
    r = obj.get('result', {})
    return (obj.get('action_id') == b['action_id'] and obj.get('action_session') == b['expected_action_session']
            and obj.get('status') in TERMINAL and r.get('input_release_confirmed') is True
            and not r.get('unknown_outcome') and not r.get('requires_handoff'))

def execute(c, b, before, monitor=True):
    """Exactly one start; cancellation at most once; unknown responses only lead to GETs."""
    c.note('intent', request=b)
    obj = {}; code = None; stopped = None; cancel_sent = False
    try:
        code, obj = c.exchange('POST', '/control/action', b)
    except Exception:
        pass
    if code not in (None, 200, 202):
        # Only a native VALIDATION no-effect proof makes a rejected start known.
        p = obj.get('native_admission', {})
        if (p.get('effects_none_proven') is True and p.get('stage') == 'validation'
                and p.get('action_id') == b['action_id'] and p.get('action_session') == b['expected_action_session']):
            return dict(known=True, no_effect=True, success=False, reason=obj.get('error', 'rejected'), action_id=b['action_id'])
        return dict(known=False, admission_rejected=True, success=False, reason=obj.get('error', 'admission_rejected_effects_not_proven'),
                    action_id=b['action_id'], response=obj)
    deadline = time.monotonic() + b.get('timeout_ms', 15000)/1000 + 10
    health = before['player']['health']
    while time.monotonic() < deadline:
        if terminal_known(obj, b):
            return dict(known=True, success=obj['status'] == 'succeeded', reason=stopped or obj.get('reason'),
                        hazard=stopped, action_id=b['action_id'], terminal=obj)
        matching = obj.get('action_id') == b['action_id'] and obj.get('action_session') == b['expected_action_session']
        if matching and obj.get('status') in TERMINAL:
            return dict(known=False, success=False, reason='terminal_release_or_effect_unknown', action_id=b['action_id'], terminal=obj)
        if monitor and matching and obj.get('status') == 'running':
            try:
                s = c.state()
                why = 'context_changed' if identity(s) != identity(before) else danger(s, health)
                if why and not cancel_sent:
                    stopped = why; cancel_sent = True
                    try:
                        c.exchange('POST', '/control/action/cancel', dict(action_id=b['action_id'], expected_action_session=b['expected_action_session']))
                    except Exception:
                        pass  # No cancellation retry; original status alone decides release.
            except Exception:
                if not cancel_sent:
                    stopped = 'monitor_read_unavailable'; cancel_sent = True
                    try:
                        c.exchange('POST', '/control/action/cancel', dict(action_id=b['action_id'], expected_action_session=b['expected_action_session']))
                    except Exception:
                        pass
        time.sleep(.2)
        try:
            code, obj = c.exchange('GET', '/control/action/status?action_id=' + b['action_id'])
            if code != 200:
                obj = {}
        except Exception:
            obj = {}
    return dict(known=False, success=False, reason='original_action_unresolved_no_reissue', action_id=b['action_id'])

def run_batch(c, actions, retreat):
    initial = c.state(); require_world(initial)
    while not initial.get('focused', False):
        c.note('waiting_for_initial_game_focus')
        time.sleep(.2)
        initial = c.state(); require_world(initial)
    context = identity(initial); previous_health = initial['player']['health']
    result = dict(status='stopped', completed=0, actions=[], retreat=None)
    danger_stop = None; safe_release = True
    try:
        for spec in actions:
            s = c.state(); require_world(s)
            if identity(s) != context:
                raise Stop('context_changed')
            danger_stop = danger(s, previous_health)
            if danger_stop:
                raise Stop(danger_stop)
            cells = None
            if spec['action'] == 'break_block':
                try:
                    cells = read_neighbours(c, s, spec['target'])
                except Stop as e:
                    if str(e).startswith(('adjacent_fluid:', 'adjacent_hazard:')):
                        danger_stop = str(e)
                    raise
            fresh = c.state(); require_world(fresh)
            if identity(fresh) != context:
                raise Stop('context_changed')
            danger_stop = danger(fresh, previous_health)
            if danger_stop:
                raise Stop(danger_stop)
            cell = None
            if cells is not None:
                check_cells(cells, needed_cells(fresh, spec['target']))
                cell = cells[tuple(spec['target'][k] for k in ('x', 'y', 'z'))]
            b = bind_action(spec, fresh, cell)
            safe_release = False
            out = execute(c, b, fresh); result['actions'].append(out)
            safe_release = out['known']
            danger_stop = out.get('hazard')
            if out.get('reason') in ('capability_damage_observed', 'capability_environment_hazard', 'capability_health_guard'):
                danger_stop = out['reason']
            if not out['known']:
                raise Stop(out['reason'])
            after = c.state(); require_world(after)
            if identity(after) != context:
                raise Stop('context_changed')
            danger_stop = danger_stop or danger(after, fresh['player']['health'])
            if danger_stop:
                raise Stop(danger_stop)
            if not out['success']:
                raise Stop(out['reason'])
            previous_health = after['player']['health']; result['completed'] += 1
        result['status'] = 'completed'; result['reason'] = 'all_actions_known_succeeded'
    except Exception as e:
        result['reason'] = str(e) if isinstance(e, Stop) else type(e).__name__
        if retreat and danger_stop and safe_release:
            try:
                s = c.state(); require_world(s)
                if identity(s) != context:
                    raise Stop('retreat_context_changed')
                # Caller supplied this already traversed route. No direction/anchor is guessed.
                b = bind_action(dict(action='follow_path', waypoints=retreat['waypoints'],
                                     timeout_ms=retreat.get('timeout_ms', 3000), sneak=True), s, guarded=False)
                result['retreat'] = execute(c, b, s, monitor=False)
            except Exception as r:
                result['retreat'] = dict(known=False, success=False, reason=str(r) if isinstance(r, Stop) else type(r).__name__)
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--retreat', type=Path)
    p.add_argument('--run-dir', type=Path, required=True)
    args = p.parse_args()
    actions = validate_plan(json.loads(args.plan.read_text()))
    retreat = validate_retreat(json.loads(args.retreat.read_text()) if args.retreat else None)
    args.run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    c = Client(args.run_dir)
    c.note('plan', actions=actions, explicit_retreat=retreat, v6_action_record=False)
    try:
        result = run_batch(c, actions, retreat)
    except Exception as e:
        result = dict(status='stopped', reason=str(e) if isinstance(e, Stop) else type(e).__name__)
    (args.run_dir/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'completed' else 1

if __name__ == '__main__':
    raise SystemExit(main())
