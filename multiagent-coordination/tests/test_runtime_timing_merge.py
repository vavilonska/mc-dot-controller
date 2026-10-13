"""Reconstructed after executor reset: actual Resident/WorldCache, synthetic bridge."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from test_resident_owner_chain import NativeFixture
from resident_controller.controller import Resident

class TimedNative(NativeFixture):
    def request(self, method, path, body=None):
        out=super().request(method,path,body)
        self.last_response_metadata={'path':path}
        if path.startswith('/control/state?'):
            out['coordination_step']['source_nano']=str(-out['world']['game_time'])
            self.last_response_metadata['sample_timing']={'game_time':out['world']['game_time'],'nano_time':-out['world']['game_time']}
        return out

class FinalStateMetadataTests(unittest.TestCase):
    def test_final_c_has_its_own_sample_and_capture_without_extra_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            native=TimedNative();resident=Resident(native,Path(tmp)/'queue');resident.start()
            try:
                out=resident.snapshot({'coordination_step':True,'terrain':True,'radius':1,'vertical':2,'frame':False})
                tick=out['state']['world']['game_time'];d=out['state_read_diagnostics'];sample=d['response_metadata']['sample_timing']
                self.assertEqual(sample,{'game_time':tick,'nano_time':-tick})
                self.assertEqual(out['state']['coordination_step']['source_nano'],str(-tick))
                self.assertEqual(d['started_monotonic'],out['coordination_capture']['started_mono'])
                self.assertEqual(d['finished_monotonic'],out['coordination_capture']['finished_mono'])
                self.assertEqual(len([c for c in native.calls if c[1].startswith('/control/state?')]),3)
                self.assertFalse([c for c in native.calls if c[0]=='POST'])
            finally:
                if resident.lock:resident.lock.close()
