import contextlib
import io
import unittest
from unittest.mock import patch
from damage_watch.__main__ import main
from test_watch import OWNER,PLAYER

class CliTests(unittest.TestCase):
    def args(self):return ['--endpoint','http://127.0.0.1:1234','--outdir','not-created-test','--expected-x','-635','--expected-y','60','--expected-z','17.2','--expected-owner',OWNER,'--expected-player',PLAYER,'--expected-next-generation','95','--expected-entry-count','94']
    def test_explicit_existing_env_token_never_printed(self):
        result={'reason':'window_not_reproduced','close_required':True};output=io.StringIO();secret='OFFLINE-SECRET-NOT-REAL'
        with patch.dict('os.environ',{'TEST_EXISTING_DIAG_TOKEN':secret}),patch('damage_watch.__main__.HttpTransport') as transport,patch('damage_watch.__main__.watch',return_value=result) as watcher,patch('damage_watch.__main__.getpass.getpass',side_effect=AssertionError('no prompt')),contextlib.redirect_stdout(output):
            self.assertEqual(main(self.args()+['--token-env','TEST_EXISTING_DIAG_TOKEN']),0);self.assertEqual(transport.call_args.args[1],secret);self.assertEqual(watcher.call_args.kwargs['expected_entry_count'],94)
        self.assertNotIn(secret,output.getvalue())
    def test_hidden_prompt_and_storage_failure_external_close_message(self):
        output=io.StringIO()
        with patch('damage_watch.__main__.getpass.getpass',return_value='offline-hidden'),patch('damage_watch.__main__.HttpTransport'),patch('damage_watch.__main__.watch',side_effect=OSError('do-not-echo-this')),contextlib.redirect_stderr(output):
            self.assertEqual(main(self.args()),2)
        self.assertIn('close_required=true',output.getvalue());self.assertNotIn('do-not-echo-this',output.getvalue())

if __name__=='__main__':unittest.main()
