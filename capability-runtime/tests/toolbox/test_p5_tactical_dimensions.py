"""P5 closed-binding/policy tests. Synthetic facts are not native or live proof."""
from copy import deepcopy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mdc_skills.core import Observation, Outcome, SkillError
from mdc_skills import threats, dimensions as skills, expedition
from mdc_toolbox.bindings import tactical, dimensions
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.contracts import ToolboxError, validate_schema
from mdc_toolbox.control import JobControl, ControlStop
from mdc_toolbox.budgets import SharedBudget
from mdc_toolbox.supervisor import LocalSupervisor
from mdc_toolbox import tactical_policy as policy


def sample(tick=1, *, hp=20, target_hp=20, target=True, dimension='minecraft:overworld', terrain=None):
    rows = [dict(uuid='target', entity_id=1, type='minecraft:zombie', alive=target_hp > 0,
                 health=target_hp, x=.5, y=64, z=2.5)] if target else []
    player = dict(x=.5, y=64, z=.5, health=hp, alive=True, on_ground=True,
                  **{key: False for key in threats.ENVIRONMENT_FLAGS})
    state = {'player': player, 'world': {'dimension': dimension, 'world_generation': 'world', 'game_time': tick},
             'nearby': {'entities': rows, 'truncated': False, 'total': len(rows), 'returned': len(rows)}}
    return Observation(state, terrain, {}, tick, ('world', dimension, 'player', 'session'), 0, 'obs-' + str(tick))


class Runtime:
    def __init__(self, observations=(), after=(), outcome='succeeded'):
        self.observations, self.after = list(observations), list(after)
        self.commands, self.outcome, self.sleeps = [], outcome, []
        self.sleeper = self.sleeps.append
    def observe(self, **kwargs):
        return self.observations.pop(0)
    def execute(self, skill, command, verify, **kwargs):
        self.commands.append((skill, command, kwargs))
        before = kwargs['before']
        after = self.after.pop(0) if self.after else before
        status = self.outcome
        if status == 'succeeded' and not verify(before, after):
            status = 'failed'
        return Outcome(status, 'verified' if status == 'succeeded' else 'postcondition_unproven',
                       ('original-action',), {}, after)
    def require_success(self, result):
        if not result.ok:
            raise SkillError(result.reason, status=result.status)
        return result.last_observation
    def result(self, skill, observations=(), **evidence):
        return Outcome('succeeded', skill, (), evidence, list(observations)[-1] if observations else None)


class Control:
    job_id = 'toolbox-job'
    def __init__(self):
        self.checks, self.events, self.stopped = 0, [], False
    def checkpoint(self):
        self.checks += 1
        if self.stopped:
            raise ControlStop('cancel_requested', status='cancelled')
    def emit(self, event, payload):
        self.events.append((event, payload))


class BindingTests(unittest.TestCase):
    def test_catalog_has_19_disjoint_bindings_and_no_live_claim(self):
        rows = tactical.definitions() + dimensions.definitions()
        self.assertEqual(len(rows), 19)
        self.assertEqual(len({row['capability'] for row in rows}), 19)
        self.assertNotIn('gateway_pearl', [row['capability'] for row in rows])
        catalog = CapabilityCatalog([tactical, dimensions])
        for row in rows:
            self.assertEqual(row['adapter_status'], 'legacy_limited')
            self.assertEqual(row['validation']['live'], 'not_run')
            self.assertFalse(row['resume_supported'])
            self.assertFalse(catalog.entry(row['capability'], {'available': True,
                'private_singleplayer': True, 'supported_capabilities': ['select_hotbar'],
                'native_features': ['capability_guard/1']})['runtime_available'])
        for name in ('end_battle', 'end_expedition'):
            self.assertEqual(catalog.get(name)['implementation_status'], 'experimental')

    def test_declared_arguments_match_current_functions(self):
        for module in (tactical, dimensions):
            for name, schema in module._SCHEMAS.items():
                names = set(inspect.signature(module._DISPATCH[name]).parameters)
                self.assertTrue(set(schema['properties']) <= names, name)
                self.assertFalse({'before', 'verify', 'resume', 'job_id'} & set(schema['properties']))

    def test_callbacks_raw_commands_and_bool_integer_rejected_before_runtime(self):
        for values in ({'target_uuid': 'target', 'verify': lambda *_: True},
                       {'target_uuid': 'target', 'before': {}},
                       {'target_uuid': 'target', 'command': {'op': 'action'}},
                       {'target_uuid': 'target', 'timeout_ms': True},
                       {'target_uuid': 'target', 'min_health': float('nan')}):
            control = Control()
            with self.assertRaises(ToolboxError):
                tactical.invoke('strike', Runtime(), values, control)
            self.assertEqual(control.checks, 0)

    def test_strike_preserves_health_loss_and_no_causal_attribution(self):
        runtime = Runtime([sample()], [sample(2, target_hp=16)])
        control = Control()
        result = tactical.invoke('strike', runtime, {'target_uuid': 'target', 'min_health': 18}, control)
        self.assertTrue(result.ok)
        self.assertEqual(runtime.commands[0][1]['min_health'], 18)
        self.assertEqual(result.evidence['observed_health_loss'], 4)
        self.assertFalse(result.evidence['damage_attributed_to_action'])
        self.assertEqual(control.checks, 1)
        self.assertEqual(control.events[0][0], 'tactical_goal_observed')

    def test_reserve20_rejects_before_any_action(self):
        runtime = Runtime([sample(hp=20)])
        with self.assertRaisesRegex(SkillError, 'health_reserve_required'):
            tactical.invoke('strike', runtime, {'target_uuid': 'target', 'min_health': 20}, Control())
        self.assertEqual(runtime.commands, [])

    def test_missing_target_is_not_kill(self):
        runtime = Runtime([sample()], [sample(2, target=False)])
        result = tactical.invoke('strike', runtime, {'target_uuid': 'target'}, Control())
        self.assertFalse(result.ok)
        self.assertNotIn('target_dead_observed', result.evidence)

    def test_unknown_defeat_does_not_retry(self):
        runtime = Runtime([sample(), sample()], outcome='unknown')
        result = tactical.invoke('defeat', runtime, {'target_uuid': 'target', 'max_actions': 8}, Control())
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(len(runtime.commands), 1)
        self.assertEqual(result.request_ids, ('original-action',))

    def test_cancel_before_dispatch_keeps_zero_actions(self):
        control, runtime = Control(), Runtime()
        control.stopped = True
        with self.assertRaises(ControlStop):
            tactical.invoke('strike', runtime, {'target_uuid': 'target'}, control)
        self.assertEqual(runtime.commands, [])

    def test_blaze_shield_window_schema_requires_complete_cycle(self):
        schema = tactical._SCHEMAS['strike']
        for args in ({'target_uuid': 'x', 'blaze_safety_mode': 'shield_window'},
                     {'target_uuid': 'x', 'blaze_safety_mode': 'shield_window', 'ranged': True, 'timeout_ms': 5000}):
            with self.assertRaises(ToolboxError): validate_schema(args, schema)
        validate_schema({'target_uuid': 'x', 'blaze_safety_mode': 'shield_window', 'ranged': True}, schema)

    def test_target_replacement_stops(self):
        after = sample(2, target_hp=16)
        after.state['nearby']['entities'][0]['entity_id'] = 2
        runtime = Runtime([sample()], [after])
        with self.assertRaisesRegex(SkillError, 'target_identity_changed'):
            tactical.invoke('strike', runtime, {'target_uuid': 'target'}, Control())
        self.assertEqual(len(runtime.commands), 1)

    def test_closed_shulker_shell_stops_before_attack(self):
        before = sample()
        before.state['nearby']['entities'][0].update(type='minecraft:shulker', shell_open=False)
        before.state['combat_capabilities'] = {'schema_version': 1, 'shulker_open_shell_guard_schema_version': 1}
        runtime = Runtime([before])
        with self.assertRaisesRegex(SkillError, 'observed_open_shell'):
            tactical.invoke('strike', runtime, {'target_uuid': 'target'}, Control())
        self.assertEqual(runtime.commands, [])

    def test_crystal_goal_is_closed_typed_data(self):
        values = {'dragon_uuid': 'dragon', 'crystals': [{'uuid': 'crystal',
            'cage_bars': [{'x': 1, 'y': 64, 'z': 1}], 'firing_station': {'x': 2, 'y': 64, 'z': 2}}]}
        with patch.dict(dimensions._DISPATCH, end_battle=lambda runtime, **args: Outcome('succeeded', 'typed', (), {'typed': args})):
            result = dimensions.invoke('end_battle', Runtime(), values, Control())
        goal = result.evidence['typed']['crystals'][0]
        self.assertIsInstance(goal, skills.CrystalGoal)
        self.assertIsInstance(goal.cage_bars, tuple)
        self.assertIsInstance(values['crystals'][0], dict)
        for extra in ('verify', 'callback', 'path'):
            bad = deepcopy(values); bad['crystals'][0][extra] = 'forbidden'
            with self.assertRaises(ToolboxError):
                dimensions.invoke('end_battle', Runtime(), bad, Control())

    def test_duplicate_crystal_and_cage_overrun_rejected(self):
        with self.assertRaisesRegex(ToolboxError, 'Duplicate'):
            dimensions.invoke('end_battle', Runtime(), {'dragon_uuid': 'dragon',
                'crystals': [{'uuid': 'same'}, {'uuid': 'same'}]}, Control())
        with self.assertRaisesRegex(ToolboxError, 'max_blocks'):
            dimensions.invoke('open_crystal_cage', Runtime(), {'crystal_uuid': 'x', 'max_blocks': 1,
                'bars': [{'x': 0, 'y': 64, 'z': 0}, {'x': 1, 'y': 64, 'z': 0}]}, Control())

    def test_dimension_transition_preserves_expected_destination(self):
        cells = [dict(x=x, y=y, z=z, id='minecraft:stone' if y == 63 else 'minecraft:air',
            status='loaded', known=True, collision_known=True, collision_empty=y != 63,
            full_top_support=y == 63, fluid='minecraft:empty', hazards=[], id_truncated=False,
            fluid_truncated=False, properties_truncated=False, properties={})
            for x in range(-1, 3) for z in range(-1, 3) for y in range(63, 66)]
        for cell in cells:
            if (cell['x'], cell['y'], cell['z']) == (1, 64, 0): cell['id'] = 'minecraft:nether_portal'
        before = sample(terrain={'complete': True, 'cells': cells,
                                'world_generation': 'world', 'dimension': 'minecraft:overworld'})
        runtime = Runtime([before], [sample(2, dimension='minecraft:the_nether')])
        result = dimensions.invoke('enter_portal', runtime, {'portal_cell': {'x': 1, 'y': 64, 'z': 0},
            'destination': 'minecraft:the_nether'}, Control())
        self.assertTrue(result.ok)
        self.assertEqual(runtime.commands[0][2]['allowed_dimension'], 'minecraft:the_nether')
        self.assertEqual(runtime.commands[0][2]['stable_samples'], 3)

    def test_phase_wait_is_bounded_read_only_and_missing_is_not_victory(self):
        runtime = Runtime([sample(1, target=False, dimension='minecraft:the_end'),
                           sample(2, target=False, dimension='minecraft:the_end')])
        result = dimensions.invoke('wait_dragon_phase', runtime, {'dragon_uuid': 'dragon', 'max_samples': 2}, Control())
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(runtime.commands, [])
        self.assertEqual(len(runtime.sleeps), 2)

    def test_expedition_no_public_resume_or_paths(self):
        for values in ({'resume': True}, {'job_id': 'old-job'}, {'path': '/tmp/checkpoint'}):
            with self.assertRaises(ToolboxError):
                dimensions.invoke('end_expedition', Runtime(), values, Control())
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(); runtime.journal_directory = Path(directory)
            path = expedition._path(runtime, 'toolbox-job'); path.write_text('old checkpoint')
            with patch.dict(dimensions._DISPATCH, end_expedition=lambda *_args, **_kwargs: self.fail('must not resume')):
                result = dimensions.invoke('end_expedition', runtime, {}, Control())
            self.assertEqual(result.reason, 'existing_expedition_checkpoint_no_resume')
            self.assertEqual(path.read_text(), 'old checkpoint')

    def test_expedition_uses_private_job_identity_only(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(); runtime.journal_directory = Path(directory)
            with patch.dict(dimensions._DISPATCH, end_expedition=lambda runtime, **kwargs: Outcome('blocked', 'fixture', (), kwargs)):
                result = dimensions.invoke('end_expedition', runtime, {'boxes': 1}, Control())
            self.assertEqual(result.evidence['job_id'], 'toolbox-job')
            self.assertIs(result.evidence['resume'], False)


def inputs():
    rules = {'version': 1, 'goal_id': 'mine-current', 'mode': 'defend', 'min_health': 12,
        'region': {'min': {'x': -8, 'y': 60, 'z': -8}, 'max': {'x': 8, 'y': 70, 'z': 8}},
        'allowed_target_uuids': ['target'], 'allow_ranged': False, 'allow_environment_recovery': True,
        'max_reactions': 2, 'max_target_distance': 8, 'max_route_distance': 4}
    facts = {'goal_id': 'mine-current', 'goal_valid': True, 'context_same': True, 'owner_known': True,
        'cleanup_confirmed': True, 'complete': True, 'player_position': {'x': 0, 'y': 64, 'z': 0},
        'health': 20, 'hazard': 'none', 'reactions_used': 0,
        'threats': [{'uuid': 'target', 'position': {'x': 2, 'y': 64, 'z': 0}, 'alive': True,
            'hostile': True, 'attacking_player': True, 'melee_eligible': True, 'ranged_eligible': False,
            'required_health_reserve': 8}],
        'routes': [{'kind': 'retreat', 'target_uuid': 'target', 'points': [{'x': -1, 'y': 64, 'z': 0}],
            'complete_loaded_safe_corridor': True, 'improves_safety': True}]}
    budget = {'remaining_seconds': 10, 'actions_remaining': 3, 'observations_remaining': 8, 'reflex_actions_remaining': 2}
    return rules, facts, budget


class PolicyTests(unittest.TestCase):
    def test_exact_authorized_threat_selects_existing_strike_without_authority(self):
        decision = policy.decide(*inputs())
        self.assertEqual(decision.action, 'strike')
        self.assertEqual(decision.target_uuid, 'target')
        self.assertFalse(decision.execution_authority)
        self.assertFalse(decision.continuation_safe)

    def test_low_health_and_species_floor_choose_retreat(self):
        for reserve, health in ((12, 12), (18, 18)):
            rules, facts, budget = inputs()
            facts['health'] = health; facts['threats'][0]['required_health_reserve'] = reserve
            self.assertEqual(policy.decide(rules, facts, budget).action, 'retreat')

    def test_unauthorized_or_mixed_threat_never_counterattacks(self):
        rules, facts, budget = inputs()
        rules['allowed_target_uuids'] = []
        self.assertEqual(policy.decide(rules, facts, budget).action, 'retreat')
        rules, facts, budget = inputs()
        second = deepcopy(facts['threats'][0]); second['uuid'] = 'other'; second['position']['x'] = 3
        facts['threats'].append(second)
        self.assertNotEqual(policy.decide(rules, facts, budget).action, 'strike')

    def test_priority_ownership_context_cleanup_and_goal_stop(self):
        for key, reason in [('owner_known', 'owner_unknown'), ('context_same', 'context_changed'),
                            ('cleanup_confirmed', 'cleanup_unconfirmed'), ('complete', 'facts_incomplete'),
                            ('goal_valid', 'goal_requires_fresh_replan')]:
            rules, facts, budget = inputs(); facts[key] = False
            decision = policy.decide(rules, facts, budget)
            self.assertEqual((decision.action, decision.reason), ('stop', reason))

    def test_original_limits_and_reaction_bound_stop(self):
        for metric in ('remaining_seconds', 'actions_remaining', 'observations_remaining', 'reflex_actions_remaining'):
            rules, facts, budget = inputs(); budget[metric] = 0
            self.assertEqual(policy.decide(rules, facts, budget).action, 'stop')
        rules, facts, budget = inputs(); facts['reactions_used'] = 2
        self.assertEqual(policy.decide(rules, facts, budget).action, 'stop')

    def test_survival_egress_precedes_counterattack(self):
        rules, facts, budget = inputs(); facts['hazard'] = 'fire'
        facts['routes'].append({'kind': 'recover_hazard', 'points': [{'x': 0, 'y': 64, 'z': 1}],
            'complete_loaded_safe_corridor': True, 'improves_safety': True})
        self.assertEqual(policy.decide(rules, facts, budget).action, 'recover_hazard')
        rules['allow_environment_recovery'] = False
        self.assertEqual(policy.decide(rules, facts, budget).action, 'stop')

    def test_unknown_outside_or_long_route_cannot_evade(self):
        for change in ('unknown', 'outside', 'long'):
            rules, facts, budget = inputs(); rules['mode'] = 'avoid'
            route = facts['routes'][0]
            if change == 'unknown': route['complete_loaded_safe_corridor'] = False
            elif change == 'outside': route['points'][0]['x'] = -9
            else: route['points'][0]['x'] = -3
            self.assertEqual(policy.decide(rules, facts, budget).action, 'stop')

    def test_closed_policy_and_facts_reject_callbacks_or_duplicate_ids(self):
        rules, facts, budget = inputs(); rules['callback'] = 'attack'
        with self.assertRaises(ToolboxError): policy.decide(rules, facts, budget)
        rules, facts, budget = inputs(); facts['threats'].append(deepcopy(facts['threats'][0]))
        with self.assertRaisesRegex(ToolboxError, 'Duplicate'): policy.decide(rules, facts, budget)

    def test_invalid_region_rejected(self):
        rules, facts, budget = inputs(); rules['region']['min']['x'] = 10
        with self.assertRaisesRegex(ToolboxError, 'region'): policy.decide(rules, facts, budget)

    def test_shared_control_ledger_not_recharged_and_stop_supervisor_latches(self):
        ledger = SharedBudget({'max_actions': 5, 'max_observations': 20,
            'reflex_reserve_actions': 2, 'cleanup_reserve_actions': 1}, 120,
            wall_clock=lambda: 100, clock=lambda: 100)
        events = []
        control = JobControl({'job_id': 'job', 'request_id': 'req', 'emit': lambda event, data: events.append((event, data))}, budget=ledger)
        supervisor = LocalSupervisor(control, {'reactions': 'stop'})
        rules, facts, _ = inputs()
        before = ledger.snapshot()
        with self.assertRaisesRegex(ControlStop, 'tactical_native_transition_unavailable'):
            policy.at_boundary(supervisor, rules, facts)
        self.assertTrue(supervisor.latched)
        self.assertEqual(before, ledger.snapshot())
        self.assertEqual(events[0][0], 'tactical_decision')
        self.assertFalse(events[0][1]['execution_authority'])
        with self.assertRaisesRegex(ControlStop, 'latched'):
            with supervisor.ordinary(): self.fail('must remain latched')

    def test_cancel_precedes_decision_and_never_emits_reflex(self):
        ledger = SharedBudget({'max_actions': 4, 'max_observations': 8,
            'reflex_reserve_actions': 1, 'cleanup_reserve_actions': 1}, 120,
            wall_clock=lambda: 100, clock=lambda: 100)
        events = []
        control = JobControl({'job_id': 'job', 'request_id': 'req', 'emit': lambda *args: events.append(args)}, budget=ledger)
        control.request_cancel('cancel-original')
        with self.assertRaisesRegex(ControlStop, 'cancel_requested'):
            policy.decide_with_control(control, *inputs()[:2])
        self.assertEqual(events, [])

class AdditionalSafetyTests(unittest.TestCase):
    def test_impossible_strike_deadlines_are_schema_rejected(self):
        for values in ({'timeout_ms': 15000}, {'timeout_ms': 20000},
                       {'timeout_ms': 20000, 'ranged': True, 'blaze_safety_mode': 'fire_resistance'}):
            with self.assertRaises(ToolboxError):
                tactical.invoke('strike', Runtime(), {'target_uuid': 'target', **values}, Control())

    def test_retreat_must_increase_actual_candidate_separation(self):
        rules, facts, budget = inputs(); rules['mode'] = 'avoid'
        facts['routes'][0]['points'][0]['x'] = 1
        self.assertEqual(policy.decide(rules, facts, budget).action, 'stop')

    def test_stop_policy_never_selects_available_attack_or_route(self):
        rules, facts, budget = inputs(); rules['mode'] = 'stop'
        self.assertEqual(policy.decide(rules, facts, budget).reason, 'caller_stop_policy')

    def test_ranged_requires_explicit_permission_and_existing_eligibility(self):
        rules, facts, budget = inputs(); facts['threats'][0]['melee_eligible'] = False
        facts['threats'][0]['ranged_eligible'] = True
        self.assertEqual(policy.decide(rules, facts, budget).action, 'retreat')
        rules['allow_ranged'] = True
        decision = policy.decide(rules, facts, budget)
        self.assertEqual(decision.action, 'strike'); self.assertTrue(decision.ranged)

    def test_unsupported_supervisor_policy_cannot_execute_registered_callback(self):
        ledger = SharedBudget({'max_actions': 4, 'max_observations': 8,
            'reflex_reserve_actions': 1, 'cleanup_reserve_actions': 1}, 120,
            wall_clock=lambda: 100, clock=lambda: 100)
        control = JobControl({'job_id': 'job', 'request_id': 'req'}, budget=ledger)
        called = []
        supervisor = LocalSupervisor(control, {'reactions': 'defend'}, reflexes={'defend': lambda *_: called.append(True)})
        with self.assertRaisesRegex(ControlStop, 'tactical_native_transition_unavailable'):
            policy.at_boundary(supervisor, *inputs()[:2])
        self.assertEqual(called, [])

    def test_domain_source_bytes_still_equal_r2_baseline(self):
        import hashlib
        # Immutable R2 source digests keep the comparison portable without private trees.
        expected = {'threats.py': 'f8105c47249c7a26da20e0d0065835a14c7070286251ea8c5f8ec74ed4a9a9f5', 'combat_goals.py': 'da85f844b3b732472c7cb8a953c77182315a219d92cf368ccd3717b64457f2be', 'dimensions.py': '07aa06b4a2527cf13ecd68ec6d3536bdbb0823bd24509da1a9260854f0d4caab', 'expedition.py': 'cb001645efed63d7a7b115054162192c98c2eda5f39f131315646be8e656c219'}
        root = Path(__file__).resolve().parents[2] / 'mdc_skills'
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, name)


if __name__ == '__main__':
    unittest.main()
