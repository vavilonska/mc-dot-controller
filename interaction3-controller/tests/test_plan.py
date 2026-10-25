import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
from interaction3_controller.plan import load_plan,Plan,validate_snapshot
from interaction3_controller.controller import Controller
from interaction3_controller.__main__ import main
from interaction3_controller.legacy import Refused,encode,strict_json
from interaction3_controller.schema import request_valid,receipt_valid,payload_digest
from support import PLAN,PLAN_DATA,PLAN_RAW,clone,Fake,request,receipt,ORIGINAL


class PlanTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def load(self,raw):
        path=self.root/'plan.json';path.write_bytes(raw)
        return load_plan(path,hashlib.sha256(raw).hexdigest())
    def test_exact_raw_hash_snapshot_immutable_copy(self):
        p=self.load(PLAN_RAW+b'\n');self.assertNotEqual(p.sha256,PLAN.sha256)
        d=p.data;d['targets'].clear();self.assertEqual(len(p.data['targets']),1)
        q=request();q['plan_sha256']=p.sha256
        self.assertEqual(validate_snapshot(p.snapshot(),q),p)
        with self.assertRaises(Refused):load_plan(self.root/'plan.json',PLAN.sha256)
    def test_closed_duplicate_nonfinite_bounded_no_links(self):
        for raw in (PLAN_RAW.replace(b'"version":1',b'"version":1,"version":1'),b'{"x":NaN}',b'x'*16385):
            with self.assertRaises(Refused):self.load(raw)
        path=self.root/'plan.json';path.write_bytes(PLAN_RAW);link=self.root/'link';link.symlink_to(path)
        with self.assertRaises(Refused):load_plan(link,PLAN.sha256)
        directory=self.root/'linked';directory.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(Refused):load_plan(directory/'plan.json',PLAN.sha256)
        with self.assertRaises(Refused):load_plan(self.root,PLAN.sha256)
    def test_closed_targets_count_catalogue_floor_context(self):
        bad=[]
        for key,value in [('version',True),('targets',[]),('targets',PLAN_DATA['targets']*9),('extra',1),('context',{})]:
            d=copy.deepcopy(PLAN_DATA);d[key]=value;bad.append(d)
        for key,value in [('block_id','minecraft:diamond_block'),('face','south'),('feet_y',61),('min_break_y',60),('pos',{'x':-635,'y':60,'z':16})]:
            d=copy.deepcopy(PLAN_DATA);d['targets'][0][key]=value;bad.append(d)
        d=copy.deepcopy(PLAN_DATA);d['targets']*=2;bad.append(d)
        for d in bad:
            with self.assertRaises(Refused):self.load(encode(d))
    def test_unbound_delivery_template_is_not_executable(self):
        path=Path(__file__).resolve().parents[2]/'plans'/'WART-PLAN-CONTEXT-UNBOUND.json'
        with self.assertRaises(Refused):self.load(path.read_bytes())
    def test_reviewed_heights_are_data_not_hardcoded61(self):
        d=copy.deepcopy(PLAN_DATA);t=d['targets'][0];t.update(feet_y=10,min_break_y=11);t['pos']['y']=11
        self.assertEqual(self.load(encode(d)).data,d)
    def test_context_and_hash_bound_before_intent(self):
        directory=self.root/'ledger';clone(directory);f=Fake()
        with Controller(directory,f,PLAN) as c:
            for key in ('session','world_generation','player_uuid','bound_owner_id'):
                f.obs=Fake().obs;f.obs[key]='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';c.observe();q=request()
                if key!='bound_owner_id':q[key]=f.obs[key]
                with self.assertRaises(Refused):c.start(q)
            f.obs=Fake().obs;c.observe();q=request();q['plan_sha256']='f'*64
            with self.assertRaises(Refused):c.start(q)
            self.assertEqual(len(c.report()['actions']),97);self.assertEqual(f.posts(),[])
    def test_missing_plan_no_effect_and_existing_id_status_stop_without_plan(self):
        directory=self.root/'ledger';clone(directory);f=Fake()
        with Controller(directory,f) as c:
            c.observe()
            with self.assertRaises(Refused):c.start(request())
        with Controller(directory,f,PLAN) as c:c.observe();q=request();c.start(q)
        with Controller(directory,f) as c:
            self.assertEqual(c.start(q)['state'],'CLOSED');c.status(q['id']);c.stop(q['id']);self.assertEqual(c.report(q['id'])['state'],'CLOSED')
            self.assertEqual(c.report(q['id'])['plan'],PLAN.snapshot())
        self.assertEqual(len(f.posts()),2)
    def test_unknown_cannot_unlock_by_replacing_valid_plan(self):
        directory=self.root/'ledger';clone(directory);f=Fake();f.fail=True
        with Controller(directory,f,PLAN) as c:c.observe();q=request();c.start(q)
        replacement=self.load(PLAN_RAW+b'\n')
        with Controller(directory,f,replacement) as c:
            c.observe();q=request();q['plan_sha256']=replacement.sha256
            with self.assertRaises(Refused):c.start(q)
            self.assertTrue(c.report()['unknown_lock'])
        self.assertEqual(len(f.posts()),1)
    def test_changed_plan_same_id_and_cli_outside_target_no_post(self):
        directory=self.root/'ledger';clone(directory);f=Fake()
        with Controller(directory,f,PLAN) as c:
            c.observe();q=request();c.start(q)
            with self.assertRaises(Refused):c.start(dict(q,plan_sha256='b'*64))
        path=self.root/'plan.json';path.write_bytes(PLAN_RAW)
        args=['--ledger',str(directory),'--endpoint',f.endpoint,'--plan',str(path),'--plan-sha256',PLAN.sha256,'--token-env','OFFLINE_FIXTURE_TOKEN','break_block','--id','ffffffff-ffff-4fff-8fff-ffffffffffff','--accept-normal-gameplay-risk','--x','-634','--y','61','--z','16','--face','SOUTH']
        before=len(f.posts())
        with patch('interaction3_controller.__main__.HttpTransport',return_value=f),contextlib.redirect_stderr(io.StringIO()):self.assertEqual(main(args),2)
        self.assertEqual(len(f.posts()),before)
    def test_request_digest_receipt_bind_plan_fields(self):
        q=request();request_valid(q);r=receipt(q);receipt_valid(r,q)
        changed=dict(q,plan_sha256='b'*64);self.assertNotEqual(payload_digest(changed),payload_digest(q))
        with self.assertRaises(Refused):receipt_valid(r,changed)
        for changed in (dict(q,plan_version=True),dict(q,plan_version=2),dict(q,plan_sha256='B'*64),{k:v for k,v in q.items() if k!='plan_sha256'}):
            with self.assertRaises(Refused):request_valid(changed)
        for changed in (dict(r,plan_version=True),dict(r,plan_sha256='c'*64)):
            with self.assertRaises(Refused):receipt_valid(changed,q)
    def test_stored_plan_raw_parsed_hash_cannot_be_silently_replaced(self):
        directory=self.root/'ledger';clone(directory);f=Fake()
        with Controller(directory,f,PLAN) as c:c.observe();q=request();c.start(q)
        data=strict_json((directory/'ledger.json').read_bytes());data['actions'][q['id']]['plan']['parsed']['targets'][0]['pos']['z']=15
        (directory/'ledger.json').write_bytes(encode(data))
        with self.assertRaises(Refused):Controller(directory,f)

if __name__=='__main__':unittest.main()
