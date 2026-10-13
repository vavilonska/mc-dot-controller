import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from mdcoord.__main__ import main
from mdcoord.demo import run_demo


class CLIChecks(unittest.TestCase):
    def test_demo_two_prepared_segments_one_writer_no_live_actions(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            result = run_demo()
        self.assertEqual(result['dispatch_count'], 2)
        self.assertEqual(result['max_writers'], 1)
        self.assertEqual([r['status'] for r in result['receipts']], ['succeeded', 'succeeded'])
        self.assertEqual(result['metrics']['counts']['scans'], 1)
        self.assertEqual(result['metrics']['counts']['observations'], 2)
        self.assertEqual(result['real_game_actions'], 0)
        self.assertFalse(result['speedup_verified'])
        self.assertFalse(result['metrics']['model_wait_available'])

    def test_cli_sanitize_outputs_unknown_original_time_and_no_secrets(self):
        output = io.StringIO()
        fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'recorded_resident_synthetic.json'
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['sanitize-result', str(fixture)]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['state_freshness'], 'unknown')
        self.assertEqual(value['observed_at_ms'], 1_700_000_000_000)
        self.assertNotIn('SYNTHETIC_SECRET', output.getvalue())

    def test_cli_has_no_live_mode_or_queue_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(['demo', '--queue', '/unused', '--live'])
        self.assertEqual(caught.exception.code, 2)

    def test_import_has_no_background_thread_or_client_creation(self):
        # Fresh interpreter avoids module cache hiding import-time behavior.
        code = "import threading,socket; n=len(threading.enumerate()); socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')); import mdcoord,mdcoord.adapters,mdcoord.__main__; assert len(threading.enumerate())==n"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
