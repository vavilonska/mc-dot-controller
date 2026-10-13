"""Explicit bounded capability gateway; no automatic game/control-process startup."""
import argparse
import json
from pathlib import Path

from .core import Runtime, SkillError
from .registry import default_registry
from .scheduler import Scheduler


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog', help='List skill contracts; no game or filesystem writes')
    check = sub.add_parser('check-goal', help='Validate one JSON goal without dispatch')
    check.add_argument('file', type=Path)
    run = sub.add_parser('run-goal', help='Explicitly run one bounded goal through an existing watchdog')
    run.add_argument('--control', type=Path, required=True, help='Already-authorized existing watchdog control directory')
    run.add_argument('--journal', type=Path, required=True, help='Private capability checkpoint directory')
    run.add_argument('--require-noncombat', action='store_true', help='Refuse a watchdog without the explicit noncombat execution policy')
    run.add_argument('--file', type=Path, required=True, help='Explicit JSON goal, unique goal_id, skill, arguments, max_actions, deadline_seconds')
    return p


def read_goal(path, registry):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SkillError('goal_file_too_large')
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data: raise SkillError('duplicate_goal_json_key')
            data[key] = value
        return data
    goal = json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(SkillError('nonfinite_goal_json')))
    if not isinstance(goal, dict) or set(goal) != {'goal_id', 'skill', 'arguments', 'max_actions', 'deadline_seconds'}:
        raise SkillError('exact_goal_schema_required')
    registry.get(goal['skill']).validate(goal['arguments'])
    return goal


def main(argv=None):
    args = parser().parse_args(argv)
    registry = default_registry()
    try:
        if args.command == 'catalog':
            print(json.dumps({'skills': registry.describe(), 'gameplay_actions': 0}, indent=2))
            return 0
        goal = read_goal(args.file, registry)
        if args.command == 'check-goal':
            print(json.dumps({'valid_shape': True, 'goal': goal, 'authorized': False, 'dispatched': False}))
            return 0
        from intent_client import IntentClient
        if not args.control.is_absolute() or not args.journal.is_absolute():
            raise SkillError('explicit_absolute_control_and_journal_paths_required')
        client = IntentClient(args.control)
        # Must already exist and be connected; this code cannot start or re-arm it.
        client.session()
        deadline = goal['deadline_seconds']
        if type(deadline) not in (int, float) or not 1 <= deadline <= 86400:
            raise SkillError('invalid_goal_deadline')
        with Runtime(client, args.journal, capability_duration_seconds=min(86400, deadline + 30),
                     required_execution_policy='noncombat' if args.require_noncombat else None) as runtime:
            scheduler = Scheduler(runtime, registry)
            scheduler.add(goal['goal_id'], goal['skill'], goal['arguments'],
                          max_actions=goal['max_actions'], deadline_seconds=goal['deadline_seconds'])
            # A new CLI lifetime freezes older pending goals, so this is the only
            # freshly admitted goal; older work requires explicit revalidation.
            result = scheduler.advance()
            goal_state = scheduler.status(goal['goal_id'])
        # Ownership release is part of clean process completion. Preserve the
        # goal's genuine semantic result if cleanup becomes uncertain.
        closed = runtime.close_outcome
        clean = closed is not None and closed.ok
        status = result.status if clean or not result.ok else (closed.status if closed else 'blocked')
        reason = result.reason if clean or not result.ok else (closed.reason if closed else 'ownership_release_not_confirmed')
        print(json.dumps({'status': status, 'reason': reason,
            'request_ids': result.request_ids, 'evidence': result.evidence,
            'goal_result': {'status': result.status, 'reason': result.reason},
            'ownership_release': {'status': closed.status, 'reason': closed.reason,
                                  'request_ids': closed.request_ids} if closed else {'status': 'not_acquired'},
            'goal': goal_state}, indent=2))
        return 0 if result.ok and clean else 2
    except (SkillError, ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({'status': getattr(exc, 'status', 'blocked'),
                          'reason': getattr(exc, 'reason', type(exc).__name__ + ':' + str(exc)),
                          'no_automatic_retry': True}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
