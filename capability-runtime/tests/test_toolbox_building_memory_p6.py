"""P6 deterministic local contracts only: no Minecraft, JVM or native acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mdc_skills.core import Observation, SkillError
from mdc_skills import building_v3
from mdc_toolbox.bindings import building, memory
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.contracts import ToolboxError, validate_schema
from mdc_toolbox.serialization import serialize_outcome
from mdc_toolbox.service import ToolboxService


def blueprint(cells=None, region=None):
    cells = cells or [{'position': {'x': 0, 'y': 64, 'z': 0},
                       'block': 'minecraft:oak_planks', 'properties': {}}]
    region = region or {'min': {'x': min(c['position']['x'] for c in cells),
        'y': min(c['position']['y'] for c in cells), 'z': min(c['position']['z'] for c in cells)},
        'max': {'x': max(c['position']['x'] for c in cells),
        'y': max(c['position']['y'] for c in cells), 'z': max(c['position']['z'] for c in cells)}}
    return building_v3.seal_blueprint({'schema_version': 3,
        'identity': {'blueprint_id': 'p6-fixture', 'revision': '1', 'source': 'deterministic-offline-test'},
        'region': region, 'cells': cells, 'clearance': [], 'light_checks': [], 'access_points': []})


class Control:
    def __init__(self):
        self.events = []
        self.checkpoints = 0
    def checkpoint(self):
        self.checkpoints += 1
    def emit(self, event, payload):
        self.events.append((event, payload))


class BuildingContracts(unittest.TestCase):
    def test_material_preview_reuses_exact_hash_and_bill_without_world_credit(self):
        spec = blueprint()
        args = {'blueprint': spec}
        before = deepcopy(args)
        with patch.object(building_v3, 'build', side_effect=AssertionError('mutation')):
            result = building.plan('build', args)
        self.assertEqual(args, before)
        self.assertEqual(result['material_bill'], building_v3.material_requirements(spec))
        self.assertEqual(result['material_bill']['items'], {'minecraft:oak_planks': 1})
        self.assertFalse(result['material_bill']['existing_world_credit'])
        self.assertFalse(result['execution_authority'])
        self.assertFalse(result['observation_used'])
        self.assertTrue(result['provenance']['content_hash_verified'])
        self.assertEqual(result['terrain_preview']['status'], 'unavailable')
        self.assertEqual(len(result['source_fingerprints']), 3)

    def test_paired_door_is_two_state_cells_one_material_item(self):
        cells = [{'position': {'x': 0, 'y': y, 'z': 0}, 'block': 'minecraft:oak_door',
                  'properties': {'facing': 'south', 'half': half, 'hinge': 'right',
                                 'open': 'false', 'powered': 'false'}}
                 for y, half in ((64, 'lower'), (65, 'upper'))]
        bill = building.plan('build_with_materials', {'blueprint': blueprint(cells)})['material_bill']
        self.assertEqual(bill['blockstate_cells'], 2)
        self.assertEqual(bill['placement_items'], 1)
        self.assertEqual(bill['items'], {'minecraft:oak_door': 1})

    def test_changed_hash_and_duplicate_cell_are_rejected(self):
        spec = blueprint()
        spec['cells'][0]['block'] = 'minecraft:stone'
        with self.assertRaisesRegex(ToolboxError, 'content_hash'):
            building.plan('build', {'blueprint': spec})
        spec = blueprint()
        spec['cells'].append(deepcopy(spec['cells'][0]))
        spec['identity']['content_sha256'] = building_v3.legacy._digest(building_v3._body(spec))
        with self.assertRaisesRegex(ToolboxError, 'duplicate'):
            building.plan('build', {'blueprint': spec})

    def test_closed_input_rejects_paths_references_callbacks_and_unknown_fields(self):
        for args in ({'blueprint_path': '/tmp/anything'}, {'blueprint_ref': 'approved-looking'},
                     {'blueprint': blueprint(), 'command': {'action': 'place_block'}},
                     {'blueprint': blueprint(), 'verify': lambda *_: True}):
            with self.subTest(args=tuple(args)):
                with self.assertRaises(ToolboxError):
                    building.plan('build', args)
        args = {'blueprint': blueprint()}
        args['blueprint']['region']['min']['ignored'] = 0
        with self.assertRaises(ToolboxError):
            building.plan('build', args)

    def test_region_access_cell_material_and_option_bounds(self):
        oversized = blueprint(region={'min': {'x': 0, 'y': 64, 'z': 0},
                                      'max': {'x': 31, 'y': 64, 'z': 0}})
        with self.assertRaisesRegex(ToolboxError, 'region_budget'):
            building.plan('build', {'blueprint': oversized})
        access = blueprint()
        access['access_points'] = [{'x': 100, 'y': 64, 'z': 0}]
        access = building_v3.seal_blueprint(access)
        with self.assertRaisesRegex(ToolboxError, 'access_point'):
            building.plan('build', {'blueprint': access})
        # Valid schema3 content outside the narrower public cell bound.
        many = [{'position': {'x': x % 27, 'y': 64, 'z': x // 27},
                 'block': 'minecraft:oak_planks', 'properties': {}} for x in range(513)]
        with self.assertRaises(ToolboxError):
            building.plan('build', {'blueprint': blueprint(many)})
        for key, value in (('max_moves', 1025), ('max_steps', True), ('hotbar_slot', 9)):
            with self.assertRaises(ToolboxError):
                building.plan('build', {'blueprint': blueprint(), key: value})

    def test_no_caller_observation_can_become_typed_history(self):
        with self.assertRaisesRegex(ToolboxError, 'trusted_typed'):
            building.plan('build', {'blueprint': blueprint()}, observation={'terrain': {'complete': True}})

    def test_total_material_types_are_bounded(self):
        blocks = sorted(building_v3.PLAIN | building_v3.LOGS)[:33]
        self.assertEqual(len(blocks), 33)
        cells = [{'position': {'x': i % 11, 'y': 64, 'z': i // 11}, 'block': block,
                  'properties': {'axis': 'y'} if block in building_v3.LOGS else {}}
                 for i, block in enumerate(blocks)]
        with self.assertRaisesRegex(ToolboxError, 'material_budget'):
            building.plan('build_with_materials', {'blueprint': blueprint(cells)})

    def test_cancellation_checkpoint_precedes_any_execution_path(self):
        control, runtime = Control(), Mock()
        control.checkpoint = Mock(side_effect=SkillError('cancel_requested', status='cancelled'))
        with self.assertRaisesRegex(SkillError, 'cancel_requested'):
            building.invoke('build', runtime, {'blueprint': blueprint()}, control)
        self.assertEqual(runtime.mock_calls, [])
        self.assertEqual(control.events, [])

    def test_typed_history_retains_original_provenance_and_blocker(self):
        observed = Observation(state={'player': {}}, terrain={'complete': False}, raw={}, tick=17,
            context=('world', 'minecraft:overworld', 'player', 'session'),
            captured_at=12.5, request_id='original-read')
        result = building.plan('build', {'blueprint': blueprint()}, observed)
        source = result['provenance']['historical_observation']
        self.assertEqual(source['request_id'], 'original-read')
        self.assertEqual(source['source_capture_monotonic'], 12.5)
        self.assertTrue(source['historical_only'])
        self.assertFalse(source['action_evidence'])
        self.assertEqual(result['terrain_preview']['reason'], 'building_complete_terrain_required')

    def test_existing_geometry_kernel_produces_effect_free_placement_preview(self):
        from test_building_v3 import OrientedRuntime
        runtime = OrientedRuntime()
        self.addCleanup(runtime.close)
        historical = runtime.survey()
        observed = Observation(state=historical.state, terrain=historical.terrain, raw={},
            tick=historical.tick, context=historical.context, captured_at=historical.captured_at,
            request_id=historical.request_id)
        original = deepcopy(observed.terrain)
        result = building.plan('build', {'blueprint': blueprint()}, observed)
        self.assertEqual(result['terrain_preview']['status'], 'available')
        self.assertEqual(len(result['terrain_preview']['placements']), 1)
        self.assertEqual(runtime.actions, [])
        self.assertEqual(observed.terrain, original)
        self.assertFalse(result['execution_authority'])

    def test_execution_is_fail_closed_even_when_called_directly(self):
        runtime, control = Mock(), Control()
        for name in ('build', 'build_with_materials'):
            outcome = building.invoke(name, runtime, {'blueprint': blueprint()}, control)
            self.assertEqual(outcome.status, 'blocked')
            self.assertEqual(outcome.request_ids, ())
            schema = next(d['result_schema'] for d in building.definitions() if d['capability'] == name)
            validate_schema(serialize_outcome(outcome), schema)
        self.assertEqual(runtime.mock_calls, [])
        self.assertEqual(control.checkpoints, 2)

    def test_real_public_plan_works_without_runtime_execution_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ToolboxService(None, directory, catalog=CapabilityCatalog([building, memory]))
            result = service.call('mdc_plan', {'api_version': 'mdc.toolbox/1', 'capability': 'build',
                'capability_version': 1, 'arguments': {'blueprint': blueprint()}})
            self.assertNotIn('error', result)
            self.assertEqual(result['material_bill']['items'], {'minecraft:oak_planks': 1})
            self.assertFalse(result['executable_authority'])
            entry = service.capabilities.entry('build', service.backend.describe())
            self.assertFalse(entry['runtime_available'])


class MemoryContracts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'knowledge.json'
        self.runtime = SimpleNamespace(journal_directory=Path(self.directory.name),
            _mutex=threading.RLock(), _owner='capture-one', clock=lambda: 20.0,
            observe=Mock(side_effect=AssertionError('native observation')),
            begin_job=Mock(side_effect=AssertionError('lease')),
            execute=Mock(side_effect=AssertionError('action')))
        self.record = {'kind': 'landmark', 'value': {'x': 1, 'y': 64, 'z': 2},
            'context': ['world-one', 'minecraft:overworld', 'player-one', 'session-one'],
            'source_tick': 14, 'source_request_id': 'original-request',
            'source_capture_monotonic': 10.0, 'capture_epoch': 'capture-one',
            'historical_only': True, 'action_evidence': False}
        self.context = dict(zip(memory._CONTEXT_NAMES, self.record['context']))

    def write(self, record=None):
        self.path.write_text(json.dumps({'schema_version': 1, 'records': {'home': self.record if record is None else record}}))

    def test_exact_read_preserves_context_timestamp_and_file_bytes(self):
        self.write()
        before = self.path.read_bytes()
        result = memory.read(self.runtime, {'query': 'home'}, {'max_results': 1}, trusted_context=self.context)
        row = result['records'][0]
        for key, value in self.record.items():
            self.assertEqual(row['record'][key], value)
        self.assertTrue(row['record']['same_context'])
        self.assertTrue(row['record']['requires_fresh_observation'])
        self.assertEqual(row['age_ms'], 10000)
        self.assertEqual(self.path.read_bytes(), before)
        self.runtime.observe.assert_not_called()
        self.runtime.begin_job.assert_not_called()
        self.runtime.execute.assert_not_called()

    def test_cross_context_is_historical_and_incomparable_epoch_has_no_fake_age(self):
        self.write()
        self.runtime._owner = 'new-runtime-epoch'
        context = dict(self.context, world_generation='other-world')
        result = memory.read(self.runtime, {'query': 'home'}, {}, trusted_context=context)
        row = result['records'][0]
        self.assertFalse(row['record']['same_context'])
        self.assertIsNone(row['age_ms'])
        self.assertFalse(result['execution_authority'])
        self.assertEqual(row['record']['source_capture_monotonic'], 10.0)

    def test_unavailable_current_context_never_claims_match(self):
        self.write()
        result = memory.read(self.runtime, {'query': 'home'}, {})
        self.assertEqual(result['context_status'], 'current_context_unavailable')
        self.assertFalse(result['records'][0]['context_comparison_available'])
        self.assertFalse(result['records'][0]['record']['same_context'])

    def test_missing_store_is_empty_read_without_creating_file(self):
        result = memory.read(self.runtime, {'query': 'missing'}, {})
        self.assertFalse(result['found'])
        self.assertEqual(result['records'], [])
        self.assertFalse(self.path.exists())

    def test_record_flags_and_provenance_fail_closed_without_repair(self):
        for changes in ({'action_evidence': True}, {'historical_only': False},
                        {'source_tick': True}, {'source_capture_monotonic': float('nan')},
                        {'context': ['world-only']}, {'value': {'text': 'a' * 8193}}):
            with self.subTest(changes=tuple(changes)):
                self.write(dict(self.record, **changes))
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ToolboxError, 'historical_memory_record'):
                    memory.read(self.runtime, {'query': 'home'}, {})
                self.assertEqual(self.path.read_bytes(), before)

    def test_path_wildcard_callback_write_and_extra_selectors_are_rejected(self):
        for selectors in ({'query': '../knowledge'}, {'query': '*'}, {'query': 'home\n'}, {'query': 'home', 'path': '/tmp/secret'},
                          {'query': 'home', 'value': {}}, {'query': lambda: 'home'}, {}):
            with self.assertRaises(ToolboxError):
                memory.read(self.runtime, selectors, {})
        with self.assertRaises(ToolboxError):
            memory.read(self.runtime, {'query': 'home'}, {'max_results': 2})

    def test_memory_symlink_is_not_followed(self):
        target = Path(self.directory.name) / 'not-authorized-records.json'
        target.write_text('{}')
        self.path.symlink_to(target)
        with self.assertRaises(ToolboxError):
            memory.read(self.runtime, {'query': 'home'}, {})

    def test_internal_query_outcome_is_data_only(self):
        self.write()
        control = Control()
        outcome = memory.invoke('memory_recall', self.runtime, {'key': 'home'}, control)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.request_ids, ())
        validate_schema(serialize_outcome(outcome), memory.definitions()[0]['result_schema'])
        with self.assertRaises(ToolboxError):
            memory.invoke('memory_remember', self.runtime, {'key': 'home'}, control)

    def test_public_observe_routes_through_real_owner_adapter_without_lease(self):
        from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
        self.write()
        original_bytes = self.path.read_bytes()
        self.runtime.has_unresolved_execution = False
        self.runtime.client = SimpleNamespace(session=lambda: {
            'state': 'ready', 'session_id': 'offline-gateway',
            'private_singleplayer': True, 'capability_lease_schema_version': 1,
            'capability_context': deepcopy(self.context)})
        backend = OwnerRuntimeBackend(self.runtime, bindings={'memory_recall': memory})
        service = ToolboxService(backend, Path(self.directory.name) / 'jobs',
                                 catalog=CapabilityCatalog([building, memory]))
        result = service.call('mdc_observe', {'api_version': 'mdc.toolbox/1',
            'session_ref': backend.describe()['session_ref'], 'profile': 'memory',
            'selectors': {'query': 'home'}, 'bounds': {'max_results': 1}})
        self.assertNotIn('error', result)
        self.assertTrue(result['records'][0]['record']['same_context'])
        self.assertEqual(result['records'][0]['record']['source_request_id'], 'original-request')
        self.assertFalse(result['executable_authority'])
        self.assertFalse(result['execution_authority'])
        self.assertEqual(service.store.all(), [])
        self.assertIsNone(backend._active)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.runtime.begin_job.assert_not_called()
        self.runtime.observe.assert_not_called()
        self.runtime.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
