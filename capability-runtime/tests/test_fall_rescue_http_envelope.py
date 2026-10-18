"""Actual Java ActionResponses wire → production Bridge HTTP → strict owner validator."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from test_fall_rescue_transport import FallTransportTests
from test_fall_rescue_evidence import COMMAND,ROWS
from resident_controller.fall_rescue_control import validate_status
HTTP_ROWS=json.loads((Path(__file__).parent/'fixtures/fall-rescue-java-http-status.json').read_text())
class FallHttpEnvelopeTests(FallTransportTests):
    def test_java_http_progression_through_real_bridge(self):
        previous=None
        for raw,plain in zip(HTTP_ROWS,ROWS,strict=True):
            self.response=json.dumps(raw).encode()
            received=self.bridge.request('GET','/control/fall-rescue/status')
            previous=validate_status(received,COMMAND,previous)
            expected=deepcopy(plain)
            episode=expected.get('episode') or expected.get('last_episode')
            if episode is not None and episode.get('interaction_result') is None:episode.pop('interaction_result',None)
            self.assertEqual(previous,expected)
        self.assertEqual(len(self.calls),5);self.assertTrue(previous['last_episode']['rescue_confirmed'])
    def test_wrapper_does_not_relax_closed_status_or_monotonic_proof(self):
        for change in ({'schema_version':True},{'schema_version':1},{'schema_version':2.0},{'protocol':'foreign'},
            {'protocol':None},{'extra':True}):
            row={**deepcopy(HTTP_ROWS[0]),**change}
            with self.subTest(change=change),self.assertRaises(ValueError):validate_status(row,COMMAND)
        for key in ('protocol','schema_version'):
            row=deepcopy(HTTP_ROWS[0]);row.pop(key)
            with self.assertRaises(ValueError):validate_status(row,COMMAND)
        with self.assertRaises(ValueError):validate_status(HTTP_ROWS[0],COMMAND,ROWS[3])
        row=deepcopy(HTTP_ROWS[4]);row['last_episode']['server_water_observed']=False
        with self.assertRaises(ValueError):validate_status(row,COMMAND)
if __name__=='__main__':unittest.main()
