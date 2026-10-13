"""Opt-in real dimension scan preserves baseline contracts and original age."""
import copy
import unittest
from unittest.mock import patch

from resident_controller.world import WorldCache
from navigation_controller.fake import FakeClock, FakeWorld, WORLD_ID
from navigation_controller.terrain import WorldStamp, CapabilityWorldStamp, TerrainAssembler, TerrainError
from test_terrain_recovery import ScriptedBridge


def capability_pages(**kwargs):
    pages = FakeWorld().pages(**kwargs)
    for page in pages:
        page.update(capability_page_schema_version=1, page_limit=1024)
    return pages


class CapabilityTerrainTests(unittest.TestCase):
    def test_legacy_stamp_still_rejects_nether(self):
        with self.assertRaisesRegex(TerrainError, 'unsupported_dimension'):
            WorldStamp(WORLD_ID, 'minecraft:the_nether', 100)
        self.assertEqual(CapabilityWorldStamp(WORLD_ID, 'minecraft:the_nether', 100).dimension,
                         'minecraft:the_nether')
        with self.assertRaisesRegex(TerrainError, 'unsupported_dimension'):
            CapabilityWorldStamp(WORLD_ID, 'mod:unknown', 100)

    def _scan(self, dimension, capability):
        clock = FakeClock()
        pages = capability_pages(radius=3, tick=100)
        for page in pages: page['dimension'] = dimension
        bridge = ScriptedBridge(clock, [pages])
        bridge.state_hook = lambda _, state: state['world'].update(dimension=dimension)
        with patch('time.monotonic', clock.monotonic), patch('time.sleep', clock.sleep):
            cache = WorldCache()
            result = cache.scan(bridge, radius=3, vertical=2, capability=capability)
            return cache, result

    def test_optin_end_and_nether_preserve_actual_dimension(self):
        for dimension in ['minecraft:the_end', 'minecraft:the_nether']:
            cache, result = self._scan(dimension, True)
            self.assertEqual(cache.grid.world.dimension, dimension)
            self.assertEqual(result['dimension'], dimension)
            self.assertEqual(result['capture_started_mono'], 100)
            self.assertEqual(result['source_tick'], 100)
            self.assertLess(result['capture_started_mono'], result['capture_finished_mono'])

    def test_legacy_output_has_no_new_metadata(self):
        _, result = self._scan('minecraft:overworld', False)
        self.assertEqual(set(result), {'origin', 'radius', 'vertical', 'world_generation', 'cells', 'complete'})

    def test_optin_rejects_mixed_dimension_page(self):
        clock = FakeClock(); pages = capability_pages(radius=3, tick=100)
        for page in pages: page['dimension'] = 'minecraft:the_end'
        pages[-1]['dimension'] = 'minecraft:the_nether'
        bridge = ScriptedBridge(clock, [pages])
        bridge.state_hook = lambda _, state: state['world'].update(dimension='minecraft:the_end')
        with patch('time.monotonic', clock.monotonic), patch('time.sleep', clock.sleep):
            with self.assertRaises(TerrainError): WorldCache().scan(bridge, 3, 2, capability=True)

    def test_capability_scan_keeps_requested_entity_radius_for_final_state(self):
        clock = FakeClock(); bridge = ScriptedBridge(clock, [capability_pages(radius=3, tick=100)])
        with patch('time.monotonic', clock.monotonic), patch('time.sleep', clock.sleep):
            WorldCache().scan(bridge, 3, 2, capability=True, entity_radius=32)
        reads = [path for method, path, body in bridge.calls if path.startswith('/control/capability-snapshot?')]
        self.assertEqual(reads, ['/control/capability-snapshot?radius=32', '/control/capability-snapshot?radius=32'])

    def test_height_extension_requires_optin_and_still_has_native_limit(self):
        cache = WorldCache()
        with self.assertRaisesRegex(ValueError, 'vertical_2_to_4'): cache.scan(None, 3, 8)
        with self.assertRaisesRegex(ValueError, 'vertical_2_to_8'): cache.scan(None, 3, 9, capability=True)
        with self.assertRaisesRegex(ValueError, 'invalid_capability'): cache.scan(None, capability='true')

if __name__ == '__main__': unittest.main()

class CapabilitySurveyTests(unittest.TestCase):
    def test_large_historical_survey_keeps_pages_and_never_promotes_navigation_cache(self):
        clock=FakeClock();pages=capability_pages(radius=16,vertical=8,tick=100)
        bridge=ScriptedBridge(clock,[pages]);cache=WorldCache()
        with patch('time.monotonic',clock.monotonic),patch('time.sleep',clock.sleep):
            result=cache.scan(bridge,16,8,capability=True,survey=True,entity_radius=128)
        self.assertTrue(result['historical_survey']);self.assertEqual(len(result['source_pages']),145)
        self.assertEqual(len(result['cells']),18513);self.assertTrue(result['complete'])
        self.assertIsNone(cache.grid);self.assertEqual(cache.cells,{})
        self.assertEqual(cache.terrain_received_at,0)
        self.assertEqual(result['source_pages'][0]['source_tick'],100)
        self.assertGreater(result['capture_finished_mono']-result['capture_started_mono'],7)
        self.assertEqual(result['source_pages'][1]['offset'],128)
    def test_wide_scan_and_long_age_do_not_leak_into_ordinary_contract(self):
        with self.assertRaises(ValueError):WorldCache().scan(None,16,8,capability=True)
        with self.assertRaises(ValueError):WorldCache().scan(None,16,8,survey=True)
        with self.assertRaises(TerrainError):TerrainAssembler(CapabilityWorldStamp(WORLD_ID,'minecraft:overworld',100),100,max_scan_ticks=320,max_scan_seconds=15)
        self.assertIsNotNone(TerrainAssembler(CapabilityWorldStamp(WORLD_ID,'minecraft:overworld',100),100,max_scan_ticks=320,max_scan_seconds=15,historical_survey=True))
    def test_survey_context_change_still_invalidates_all_cells(self):
        clock=FakeClock();pages=capability_pages(radius=3,vertical=2,tick=100)
        bridge=ScriptedBridge(clock,[pages]);cache=WorldCache()
        bridge.state_hook=lambda n,s:s['player'].update(uuid='replaced' if n>1 else 'original')
        with patch('time.monotonic',clock.monotonic),patch('time.sleep',clock.sleep):
            with self.assertRaisesRegex(TerrainError,'context_changed'):cache.scan(bridge,3,2,capability=True,survey=True)
        self.assertIsNone(cache.grid)
