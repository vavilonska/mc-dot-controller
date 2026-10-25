"""Offline compatibility, no actual native network or tokens."""
import base64
import copy
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from interaction_controller.legacy import legacy, encode, strict_json, Refused, RawReply
from interaction_controller.journal import JournalController

FROZEN_FIXTURES=Path(__file__).resolve().parents[2]/'short-input-controller'/'tests'/'fixtures'
OWNER='11111111-1111-4111-8111-111111111111'
ENDPOINT='http://127.0.0.1:38121'


def synthetic_legacy(directory,count=57,state='CLOSED'):
    directory.mkdir(mode=0o700)
    actions={}
    for generation in range(1,count+1):
        req=strict_json((FROZEN_FIXTURES/'request.json').read_bytes())
        req.update(id=str(uuid4()),owner_generation=generation)
        terminal=strict_json((FROZEN_FIXTURES/'status-settled.json').read_bytes())
        terminal.update(id=req['id'],owner_generation=generation,payload_digest=legacy.payload_digest(req))
        record=dict(request=req,state=state,unknown_reasons=[],evidence=[dict(kind='start',http_status=200,complete=True,raw_base64=base64.b64encode(encode(terminal)).decode())],latest_native=terminal,terminal_native=terminal,stop_attempted=False)
        actions[req['id']]=record
    data=dict(version=1,endpoint=ENDPOINT,actions=actions,unknown_lock=state=='UNKNOWN')
    for name,value in (('ledger.json',data),('owner.json',{'owner_id':OWNER})):
        path=directory/name;path.write_bytes(encode(value));path.chmod(0o600)
    (directory/'owner.lock').touch(mode=0o600)
    return copy.deepcopy(data)


class NoNetwork:
    endpoint=ENDPOINT
    def __init__(self):self.calls=[]
    def request(self,*args):self.calls.append(args);raise AssertionError('no network in compatibility fixture')


class LegacyTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)/'ledger';self.transport=NoNetwork()
    def tearDown(self):self.temp.cleanup()
    def test_57_known_history_owner_and_evidence_preserved(self):
        original=synthetic_legacy(self.directory)
        owner=(self.directory/'owner.json').read_bytes()
        with JournalController(self.directory,self.transport) as c:
            self.assertEqual(c.report(),original);self.assertEqual(c.owner_id,OWNER)
        self.assertEqual(strict_json((self.directory/'ledger.json').read_bytes()),original)
        self.assertEqual((self.directory/'owner.json').read_bytes(),owner);self.assertEqual(self.transport.calls,[])
    def test_old_pending_and_unknown_persist_without_dispatch(self):
        original=synthetic_legacy(self.directory,state='PENDING')
        with JournalController(self.directory,self.transport) as c:
            self.assertTrue(c.report()['unknown_lock'])
            for aid,record in c.report()['actions'].items():
                self.assertEqual(record['state'],'UNKNOWN')
                for key in ('request','terminal_native','evidence'):self.assertEqual(record[key],original['actions'][aid][key])
        with JournalController(self.directory,self.transport) as c:self.assertTrue(c.report()['unknown_lock'])
        self.assertEqual(self.transport.calls,[])
    def test_empty_or_missing_owner_never_bootstraps(self):
        with self.assertRaises(Refused):JournalController(self.directory,self.transport)
        self.assertFalse(self.directory.exists())
        synthetic_legacy(self.directory);(self.directory/'owner.json').unlink()
        with self.assertRaises(Refused):JournalController(self.directory,self.transport)
        self.assertFalse((self.directory/'owner.json').exists())
    def test_legacy_status_and_stop_use_retained_route(self):
        original=synthetic_legacy(self.directory);aid=next(iter(original['actions']));record=original['actions'][aid]
        class Fixture(NoNetwork):
            def request(self,method,path,body=None):
                self.calls.append((method,path,body));return RawReply(200,encode(record['terminal_native']))
        f=Fixture()
        with JournalController(self.directory,f) as c:
            c.status(aid);c.stop(aid);c.stop(aid)
        self.assertEqual([x[0] for x in f.calls],['GET','POST'])
        self.assertTrue(all(x[1].startswith(legacy.ROOT) for x in f.calls))
        self.assertEqual(f.calls[1][2]['profile'],legacy.PROFILE)
        self.assertEqual(f.calls[1][2]['owner_id'],OWNER)

if __name__=='__main__':unittest.main()
