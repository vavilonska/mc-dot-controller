"""Owner-run read-only probe or ONE explicitly approved guarded action.

Importing this module makes no connection. No token files/environment variables
are read. The command prompts the owner without echo and never saves the token.
"""
from dataclasses import asdict
import argparse
import getpass
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import warnings
from .executor import wrap_yaw
from .observation import Position
from .reader import collect_terrain
from .sample_adapter import GuardedSampleAdapter, SampleConfig, SampleError
from .terrain import TerrainError, WorldStamp, integer, number, protocol, uuid


class ProbeError(ValueError):
    pass


# Explicit local codes only. Never copy arbitrary exception text, missing-key
# values, server bodies, token strings, raw URLs or authentication headers.
SAFE_ERROR_CODES = frozenset('''
invalid_start_delay invalid_arguments_use_help explicit_acceptance_flags_required
read_only_mode_has_action_arguments expected_session_fingerprint_required
invalid_acceptance_duration invalid_turn_degrees invalid_acceptance_action
transport_acceptance_required session_fingerprint_mismatch not_in_world
invalid_session_identity session_changed state_identity_mismatch
report_destination_unavailable interactive_hidden_token_prompt_required
secure_token_prompt_unavailable invalid_loopback_base_url invalid_caller_token
invalid_transport_flags invalid_transport_timeout invalid_transport_config
transport_closed transport_busy operation_deadline request_failed
unexpected_http_status invalid_response_headers invalid_response_content_type
invalid_response_encoding invalid_response_length invalid_response_json
invalid_response_type response_too_large truncated_response read_not_allowlisted
invalid_integer invalid_number invalid_uuid invalid_coordinate
unsupported_protocol unsupported_dimension unsupported_terrain_schema
invalid_or_stale_terrain_page invalid_cell_count invalid_cell_status invalid_known_flag
invalid_unknown_flag invalid_unknown_count invalid_total invalid_completion
invalid_budget_flag invalid_cursor mixed_scan cell_order_mismatch noncontiguous_page
page_tick_mismatch invalid_scan_duration scan_budget_or_completed scan_invalidated
scan_tick_budget stale_terrain_clock stale_terrain_ticks terrain_from_future
world_generation_changed incomplete_scan incomplete_or_invalidated_scan
scan_wall_budget_exhausted scan_page_budget_exhausted position_out_of_bounds
'''.split())


def safe_failure(exc, progress, *, action=False):
    from .http_transport import TransportError
    code='probe_or_transport_failed'
    if isinstance(exc,(ProbeError,TransportError,TerrainError)):
        if len(exc.args)==1 and type(exc.args[0]) is str and exc.args[0] in SAFE_ERROR_CODES:
            code=exc.args[0]
        elif isinstance(exc,TerrainError):
            code='terrain_validation_failed'
    elif isinstance(exc,KeyError):
        code='missing_response_field'
    elif isinstance(exc,(TypeError,AttributeError)):
        code='invalid_response_shape'
    result={'result':'stopped','code':code,'stage':progress['stage'],'input_retried':False}
    if action:
        result.update(mode='one_action_local_test',cleanup_verified=False,further_actions_allowed=False)
    else:
        result.update(mode='read_only',input_sent=False)
    status=getattr(exc,'http_status',None) if isinstance(exc,TransportError) else None
    if code=='unexpected_http_status' and type(status) is int and 100 <= status <= 599:
        result['http_status']=status
    return result


def emit_report(output, report_handle):
    """Preserve a sanitized success or failure report; never imply a safe retry."""
    text=json.dumps(output,indent=2,allow_nan=False)+'\n'
    failed=False
    interrupted=False
    if report_handle is not None:
        try:
            report_handle.write(text)
            report_handle.flush()
        except (Exception,KeyboardInterrupt) as exc:
            failed=True
            interrupted=isinstance(exc,KeyboardInterrupt)
            output=dict(output,report_saved=False,report_error='report_write_failed')
            text=json.dumps(output,indent=2,allow_nan=False)+'\n'
    try:
        print(text,end='')
    except (Exception,KeyboardInterrupt) as exc:
        # A closed output stream must not cause a second report append or hide
        # an already recorded action count behind a fresh generic failure.
        failed=True
        interrupted=interrupted or isinstance(exc,KeyboardInterrupt)
    return 130 if interrupted else int(failed)


class RealClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def session_identity(status):
    protocol(status)
    if status.get('in_world') is not True or status.get('bridge_running') is not True:
        raise ProbeError('not_in_world')
    run = status['run_id']
    if not isinstance(run, str) or not run or len(run)>160:
        raise ProbeError('invalid_session_identity')
    return (run, integer(status['process_id'],1), uuid(status['player']['uuid']),
            uuid(status['world']['world_generation']))


def session_fingerprint(status):
    # A digest identifies the exact session without printing player UUID/run/path.
    identity = session_identity(status)
    movement_session = uuid(status['guarded_movement']['session'])
    return hashlib.sha256(json.dumps([*identity,movement_session],separators=(',',':')).encode()).hexdigest()


def cleanup_summary(status):
    guard = status.get('guarded_movement',{})
    neutral = (status.get('held_mappings') == []
               and status.get('mouse',{}).get('held_world_buttons') == []
               and all(status.get('mouse',{}).get(k) is False for k in ('left_pressed','right_pressed','middle_pressed')))
    complete = all(key in guard for key in ('owner_request_id','owner_action','sampled','released'))
    return {'ownership_metadata_complete':complete,
            'guard_cleanup_quiescent': bool(complete and guard['owner_request_id'] is None
                and guard['owner_action'] is None and guard['sampled'] is False and guard['released'] is True),
            'ordinary_inputs_neutral':neutral}


def read_only_probe(transport, clock, progress=None):
    """Bounded observations only. No POST or external state/configuration changes."""
    progress={} if progress is None else progress
    progress['stage']='capabilities'
    capability=transport.request('GET','/control/capabilities');protocol(capability)
    progress['stage']='initial_status'
    initial=transport.request('GET','/control/status');protocol(initial)
    report={'mode':'read_only','input_sent':False,'protocol_ok':True,'in_world':initial.get('in_world') is True,
            'movement_enabled':capability.get('guarded_movement',{}).get('enabled') is True,
            'turn_enabled':capability.get('guarded_turn',{}).get('enabled') is True,
            'cleanup':cleanup_summary(initial)}
    if not report['in_world']:
        report['result']='local_world_required_for_terrain'
        return report
    initial_identity=session_identity(initial)
    fingerprint=session_fingerprint(initial)
    def world():
        progress['stage']='terrain_status'
        status=transport.request('GET','/control/status')
        if session_identity(status)!=initial_identity or session_fingerprint(status)!=fingerprint:
            raise ProbeError('session_changed')
        return WorldStamp.parse(status['world'])
    def terrain(path):
        progress['stage']='terrain_page'
        return transport.request('GET',path)
    grid=collect_terrain(terrain,world,clock,radius=1,vertical=1,max_pages=27,max_seconds=2)
    progress['stage']='player_state'
    state=transport.request('GET','/control/state?radius=4');protocol(state)
    progress['stage']='final_status'
    final=transport.request('GET','/control/status');protocol(final)
    progress['stage']='validate_observations'
    if session_identity(final)!=initial_identity or session_fingerprint(final)!=fingerprint:
        raise ProbeError('session_changed')
    state_world=WorldStamp.parse(state['world']); final_world=WorldStamp.parse(final['world'])
    if (not state_world.same_world(final_world) or state['player'].get('uuid')!=initial_identity[2]
            or state['player'].get('dimension')!=final_world.dimension
            or not integer(initial['world']['game_time'],0) <= state_world.tick <= final_world.tick):
        raise ProbeError('state_identity_mismatch')
    grid.require_fresh(final_world,clock.monotonic())
    p=state['player']; Position.parse(p); velocity=Position.parse(p['velocity'])
    report.update(result='read_only_observations_verified',session_fingerprint=fingerprint,
                  dimension=final_world.dimension,
                  terrain={'cells':len(grid.cells),'complete':grid.complete,
                           'clear_cells':sum(c.clear for c in grid.cells.values()),
                           'supported_floor_cells':sum(c.support for c in grid.cells.values()),
                           'oldest_age_ticks':final_world.tick-grid.first_tick},
                  player={'health_full':number(p['health'])==number(p['max_health']),
                          'on_ground':p.get('on_ground') is True,
                          'horizontal_speed':math.hypot(velocity.x,velocity.z),
                          'yaw':wrap_yaw(number(p['yaw']))},
                  nearby_radius=number(state['nearby']['radius']),cleanup=cleanup_summary(final),
                  live_navigation_accepted=False)
    return report


def one_action_test(transport, clock, *, action, expected_session, turn_degrees=0,
                    max_seconds=2.0, accept_local_test=False, accept_installed_guard_build=False,
                    accept_unpublished_survival=False):
    """Exactly one turn OR one forward sample, never a route/autonomous loop."""
    if not all(v is True for v in (accept_local_test,accept_installed_guard_build,accept_unpublished_survival)):
        raise ProbeError('explicit_acceptance_flags_required')
    if action not in ('turn','forward-sample'):
        raise ProbeError('invalid_acceptance_action')
    if not isinstance(expected_session,str) or len(expected_session)!=64 or any(c not in '0123456789abcdef' for c in expected_session):
        raise ProbeError('expected_session_fingerprint_required')
    if not .5 <= number(max_seconds) <= 5:
        raise ProbeError('invalid_acceptance_duration')
    if (action=='turn' and not 0 < abs(number(turn_degrees)) <= 29.99) or (action!='turn' and turn_degrees!=0):
        raise ProbeError('invalid_turn_degrees')
    if getattr(getattr(transport,'config',None),'enabled',None) is not True or getattr(transport.config,'acceptance_verified',None) is not True:
        raise ProbeError('transport_acceptance_required')
    started=clock.monotonic()
    status=transport.request('GET','/control/status')
    if session_fingerprint(status)!=expected_session:
        raise ProbeError('session_fingerprint_mismatch')
    identity=session_identity(status)
    adapter=GuardedSampleAdapter(transport,clock,identity,
        SampleConfig(enabled=True,acceptance_verified=True,max_actions=1,max_samples=1,
                     max_seconds=max_seconds,settle_seconds=min(1.0,max_seconds),settle_reads=16),
        expected_movement_session=uuid(status['guarded_movement']['session']))
    try:
        adapter.prepare()
        context=adapter.observe()
        before=context.observation
        if action=='turn':
            fresh=adapter.turn(context,wrap_yaw(context.canonical_yaw+turn_degrees),started+max_seconds)
        else:
            fresh=adapter.forward_sample(context,started+max_seconds)
        after=fresh.observation
        return {'mode':'one_action_local_test','requested_action':action,'result':'readback_verified',
                'actions':adapter.actions,'samples':adapter.samples,'cleanup_verified':adapter.cleanup_verified,
                'settled_displacement_blocks':round(after.position.distance(before.position),6),
                'yaw_change_degrees':round(wrap_yaw(fresh.canonical_yaw-context.canonical_yaw),6),
                'elapsed_seconds':round(clock.monotonic()-started,4),'live_navigation_accepted':False}
    except Exception as exc:
        # SampleError values are our fixed local codes, never raw peer bodies.
        reason=str(exc) if isinstance(exc,SampleError) else 'action_validation_failed'
        # Do not retry or fall back to legacy release. Stop admission locally.
        return {'mode':'one_action_local_test','requested_action':action,'result':'stopped','reason':reason,
                'actions':adapter.actions,'samples':adapter.samples,'cleanup_verified':adapter.cleanup_verified,
                'further_actions_allowed':False,'live_navigation_accepted':False}
    finally:
        adapter.stop()


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self,message):
        # Never echo unknown argv, which could contain an accidentally pasted secret.
        raise ProbeError('invalid_arguments_use_help')


def parser():
    p=SafeArgumentParser(description='Read-only bridge probe by default; optionally one explicitly approved guarded local test.')
    p.add_argument('--url',required=True,help='Explicit http://127.0.0.1:PORT or http://[::1]:PORT')
    p.add_argument('--action',choices=('read-only','turn','forward-sample'),default='read-only')
    p.add_argument('--expected-session',help='Fingerprint from your immediately preceding read-only report')
    p.add_argument('--turn-degrees',type=float,default=0)
    p.add_argument('--max-seconds',type=float,default=2)
    p.add_argument('--start-delay',type=float,default=0,
                   help='Owner-selected 0–15 seconds after hidden token entry, before any reads; return focus to the game yourself')
    p.add_argument('--accept-local-test',action='store_true')
    p.add_argument('--accept-installed-guard-build',action='store_true')
    p.add_argument('--accept-unpublished-survival',action='store_true')
    p.add_argument('--report',help='New local JSON report path; existing files are not overwritten')
    return p


def main(argv=None):
    transport=None
    output=None
    report_handle=None
    action=False
    progress={'stage':'arguments'}
    try:
        args=parser().parse_args(argv)
        if not math.isfinite(args.start_delay) or not 0 <= args.start_delay <= 15:
            raise ProbeError('invalid_start_delay')
        action=args.action!='read-only'
        if action and not (args.accept_local_test and args.accept_installed_guard_build and args.accept_unpublished_survival):
            raise ProbeError('explicit_acceptance_flags_required')
        if not action and (args.expected_session or args.turn_degrees!=0 or args.accept_local_test
                           or args.accept_installed_guard_build or args.accept_unpublished_survival):
            raise ProbeError('read_only_mode_has_action_arguments')
        if action:
            if (not isinstance(args.expected_session,str) or len(args.expected_session)!=64
                    or any(c not in '0123456789abcdef' for c in args.expected_session)):
                raise ProbeError('expected_session_fingerprint_required')
            if not .5 <= number(args.max_seconds) <= 5:
                raise ProbeError('invalid_acceptance_duration')
            if ((args.action=='turn' and not 0 < abs(number(args.turn_degrees)) <= 29.99)
                    or (args.action!='turn' and args.turn_degrees!=0)):
                raise ProbeError('invalid_turn_degrees')
        if args.report:
            progress['stage']='reserve_report'
            try:
                report_handle=Path(args.report).open('x',encoding='utf-8')
            except OSError:
                raise ProbeError('report_destination_unavailable') from None
        progress['stage']='hidden_token_prompt'
        if not sys.stdin.isatty():
            raise ProbeError('interactive_hidden_token_prompt_required')
        # Source import only; connection opens solely when an owner runs the command.
        from .http_transport import LoopbackConfig, LoopbackHttpTransport
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                token=getpass.getpass('Bridge token (hidden; not saved): ')
        except getpass.GetPassWarning:
            raise ProbeError('secure_token_prompt_unavailable') from None
        progress['stage']='configure_transport'
        transport=LoopbackHttpTransport(LoopbackConfig(base_url=args.url,token=token,
            enabled=action,acceptance_verified=action))
        token=None
        if args.start_delay:
            progress['stage']='owner_focus_delay'
            # No connection/observation yet. This is only a manual focus handoff;
            # all fresh-read and action clocks begin afterward with unchanged limits.
            print(f'Starting in {args.start_delay:g} seconds; return focus to Minecraft yourself.',
                  file=sys.stderr,flush=True)
            time.sleep(args.start_delay)
        if action:
            progress['stage']='one_action_acceptance'
            output=one_action_test(transport,RealClock(),action=args.action,expected_session=args.expected_session,
                turn_degrees=args.turn_degrees,max_seconds=args.max_seconds,
                accept_local_test=args.accept_local_test,accept_installed_guard_build=args.accept_installed_guard_build,
                accept_unpublished_survival=args.accept_unpublished_survival)
        else:
            output=read_only_probe(transport,RealClock(),progress)
        report_status=emit_report(output,report_handle)
        return report_status or (1 if output.get('result')=='stopped' else 0)
    except KeyboardInterrupt:
        interrupted={'result':'interrupted','cleanup_verified':False,'input_retried':False,'stage':progress['stage']}
        if not action:interrupted.update(mode='read_only',input_sent=False)
        emit_report(interrupted,report_handle)
        return 130
    except Exception as exc:
        emit_report(safe_failure(exc,progress,action=action),report_handle)
        return 1
    finally:
        if transport is not None:transport.close()
        if report_handle is not None:
            try:report_handle.close()
            except Exception:pass


if __name__=='__main__':
    raise SystemExit(main())
