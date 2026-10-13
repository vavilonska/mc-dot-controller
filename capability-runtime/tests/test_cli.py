import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class CliTests(unittest.TestCase):
    def test_catalog_is_read_only_and_concrete(self):
        result=subprocess.run([sys.executable,'-m','mdc_skills','catalog'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['gameplay_actions'],0)
        self.assertGreaterEqual(len(data['skills']),33)
    def test_help_requires_explicit_paths_for_execution(self):
        result=subprocess.run([sys.executable,'-m','mdc_skills','run-goal','--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('--control',result.stdout)
        self.assertIn('--journal',result.stdout)
    def test_goal_check_not_authorization_or_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'goal.json'
            path.write_text(json.dumps({'goal_id':'reach-one','skill':'navigate','arguments':{'goal':{'x':1,'y':64,'z':0}},'max_actions':1,'deadline_seconds':30}))
            result=subprocess.run([sys.executable,'-m','mdc_skills','check-goal',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(result.stdout)
            self.assertFalse(data['dispatched']);self.assertFalse(data['authorized'])
    def test_duplicate_goal_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'goal.json';path.write_text('{"goal_id":"a","goal_id":"b"}')
            result=subprocess.run([sys.executable,'-m','mdc_skills','check-goal',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('duplicate_goal_json_key',result.stdout)
    def test_cli_waits_for_close_and_does_not_report_uncertain_release_as_success(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch, MagicMock
        from mdc_skills.__main__ import main
        from mdc_skills.core import Outcome
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'goal.json'
            path.write_text(json.dumps({'goal_id':'reach-one','skill':'navigate','arguments':{'goal':{'x':1,'y':64,'z':0}},'max_actions':1,'deadline_seconds':8000}))
            runtime=MagicMock(); runtime.__enter__.return_value=runtime
            runtime.close_outcome=None
            def close(*args):
                runtime.close_outcome=Outcome('unknown','ownership_control_unknown:OSError')
            runtime.__exit__.side_effect=close
            scheduler=MagicMock();scheduler.advance.return_value=Outcome('succeeded','goal_observed')
            scheduler.status.return_value={'status':'succeeded'}
            output=io.StringIO()
            with patch('mdc_skills.__main__.Runtime',return_value=runtime) as constructor, patch('mdc_skills.__main__.Scheduler',return_value=scheduler), patch('intent_client.IntentClient'), redirect_stdout(output):
                code=main(['run-goal','--control',directory,'--journal',directory,'--file',str(path),'--require-noncombat'])
            value=json.loads(output.getvalue())
            self.assertEqual(code,2)
            self.assertEqual(value['status'],'unknown')
            self.assertEqual(value['goal_result']['status'],'succeeded')
            self.assertEqual(value['ownership_release']['status'],'unknown')
            self.assertEqual(constructor.call_args.kwargs['capability_duration_seconds'],8030)
            self.assertEqual(constructor.call_args.kwargs['required_execution_policy'],'noncombat')

if __name__=='__main__':unittest.main()
