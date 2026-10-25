import base64
import copy
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from interaction2_controller.controller import Controller
from interaction2_controller.legacy import Refused,encode,strict_json,MAX_RESPONSE,PROFILE,RawReply
from interaction2_controller.schema import payload_digest
from interaction2_controller.__main__ import assess,main
from support import clone,ORIGINAL,OWNER,Fake,request,record,receipt,ENDPOINT,observation,PLAN


class ControllerTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.directory=Path(self.tmp.name)/'ledger';clone(self.directory);self.f=Fake();self.c=Controller(self.directory,self.f,PLAN)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def submit(self,kind='break_block',**updates):
        q=request(kind);q.update(updates);self.c.observe();return q,self.c.start(q)
    def test_real94_history_owner_digest_raw_evidence_immutable(self):
        self.assertEqual(self.c.report(),ORIGINAL);self.assertEqual(self.c.owner_id,OWNER)
        for kind in ('move','look','select_hotbar','break_block'):self.submit(kind)
        for aid,old in ORIGINAL['actions'].items():self.assertEqual(self.c.report(aid),old)
        self.c.close();self.c=Controller(self.directory,self.f,PLAN);self.assertEqual(len(self.c.report()['actions']),98)
        self.assertEqual(strict_json((self.directory/'owner.json').read_bytes()),{'owner_id':OWNER})
    def test_original_id_dedup_across_three_profiles_and_kind(self):
        q,_=self.submit();self.c.start(q);self.assertEqual(len(self.f.posts()),1)
        for old in ORIGINAL['actions'].values():
            self.c.start(old['request'])
            with self.assertRaises(Refused):self.c.start(dict(q,id=old['request']['id']))
        changed=request('look');changed['id']=q['id']
        with self.assertRaises(Refused):self.c.start(changed)
        self.assertEqual(len(self.f.posts()),1)
    def test_old_pending_unknown_global_across_new_world(self):
        old_id=next(iter(ORIGINAL['actions']));self.c.ledger.data['actions'][old_id]['state']='PENDING';self.c.ledger.save();self.c.close();self.c=Controller(self.directory,self.f,PLAN)
        self.assertTrue(self.c.report()['unknown_lock']);self.assertEqual(self.c.report(old_id)['state'],'UNKNOWN')
        self.f.obs['world_generation']=str(uuid4())
        with self.assertRaises(Refused):self.submit('look',world_generation=self.f.obs['world_generation'])
        self.assertEqual(self.f.posts(),[])
    def test_lost_response_status_stop_and_restart_stay_unknown(self):
        self.f.fail=True;q,result=self.submit();self.assertEqual(result['state'],'UNKNOWN')
        self.c.status(q['id']);self.c.stop(q['id']);self.c.stop(q['id']);self.c.start(q)
        self.assertEqual(len(self.f.posts()),2);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
        self.c.close();self.c=Controller(self.directory,self.f,PLAN)
        with self.assertRaises(Refused):self.submit('move')
    def test_remaining_is_observed_not_old_damage_band_or_magic131(self):
        self.f.obs['hotbar'][2].update(damage=500,max_damage=501)
        _,result=self.submit();self.assertEqual(result['state'],'CLOSED');self.assertEqual(result['local_risk']['observed_tool_remaining'],1)
        self.assertEqual(assess(result)[0],4) # known unchanged is not UNKNOWN or a successful break
    def test_missing_zero_or_exhausted_max_damage_refuses_before_intent(self):
        for update in ({'damage':131,'max_damage':131},{'damage':0,'max_damage':0},{'damage':132,'max_damage':131},{'max_damage':True}):
            self.f.obs=observation();self.f.obs['hotbar'][2].update(update)
            with self.assertRaises(Refused):self.submit()
        self.f.obs=observation();self.f.obs['hotbar'][2].pop('max_damage')
        with self.assertRaises(Refused):self.submit()
        self.assertEqual(self.f.posts(),[]);self.assertEqual(len(self.c.report()['actions']),94)
    def test_compiled_target_face_min_y_feet_and_tool_only(self):
        for change in ({'x':-636},{'y':60},{'face':'NORTH'},{'block_id':'minecraft:cobblestone'},{'max_calls':33}):
            with self.assertRaises(Refused):self.submit(**change)
        self.f.obs['pose']['y']=59.
        with self.assertRaises(Refused):self.submit()
        self.f.obs=observation();self.f.obs['hotbar'][2]['item_id']='minecraft:stone_hoe'
        with self.assertRaises(Refused):self.submit()
        self.assertEqual(self.f.posts(),[])
    def test_live_ray_and_fullstack_binding(self):
        for change in ({'kind':'entity'},{'face':'NORTH'},{'x':-634}):
            self.f.obs=observation();self.f.obs['ray'].update(change)
            with self.assertRaises(Refused):self.submit()
        self.f.obs=observation();self.f.obs['hotbar'][2]['stack_fingerprint']='b'*64
        with self.assertRaises(Refused):self.submit()
        self.assertEqual(self.f.posts(),[])
    def test_jump_placement_combat_and_unbounded_look_refused(self):
        for kind,changes in (('move',{'jump_first':True}),('look',{'yaw':180.}),('look',{'yaw':0.}),('look',{'pitch':float('nan')})):
            with self.assertRaises(Refused):self.submit(kind,**changes)
        for kind in ('place_block','combat','batch'):
            q=request();q['kind']=kind
            with self.assertRaises(Refused):self.c.start(q)
        self.assertEqual(self.f.posts(),[])
    def test_durable_before_first_post_and_fsync_fault_no_post(self):
        def check(method,path,body):
            if path.endswith('start'):
                disk=strict_json((self.directory/'ledger.json').read_bytes());self.assertEqual(disk['actions'][body['id']]['request'],body);self.assertEqual(disk['actions'][body['id']]['state'],'PENDING')
        self.f.before=check;self.submit('look')
        q=request('look');self.c.observe();before=len(self.f.posts())
        with patch.object(self.c.ledger,'save',side_effect=OSError('offline fsync fixture')):
            with self.assertRaises(OSError):self.c.start(q)
        self.assertEqual(len(self.f.posts()),before)
    def test_new_byte_guard_includes_record_before_adding_intent(self):
        # Synthetic padding only in a temporary clone; no actual historical evidence is pruned.
        data=self.c.ledger.data;aid=next(iter(data['actions']));data['actions'][aid]['capacity_fixture_padding']=''
        target=self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-1000
        data['actions'][aid]['capacity_fixture_padding']='x'*(target-len(encode(data)));self.c.ledger.save()
        disk=(self.directory/'ledger.json').read_bytes();q=request();self.c.observe()
        with self.assertRaises(Refused):self.c.start(q)
        self.assertNotIn(q['id'],self.c.report()['actions']);self.assertEqual(self.f.posts(),[])
        self.assertEqual((self.directory/'ledger.json').read_bytes(),disk)
    def test_near_byte_ceiling_keeps_existing_status_stop_reserve(self):
        self.f.state='ACTIVE';q,_=self.submit('look')
        data=self.c.ledger.data;aid=next(iter(ORIGINAL['actions']));data['actions'][aid]['capacity_fixture_padding']=''
        target=self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-10000
        data['actions'][aid]['capacity_fixture_padding']='x'*(target-len(encode(data)));self.c.ledger.save()
        self.c.status(q['id']);self.f.state='SETTLED';self.c.stop(q['id']);self.c.status(q['id'])
        self.assertEqual(self.c.report(q['id'])['state'],'CLOSED');self.assertEqual(len(self.f.posts()),2)
        self.assertLess(len(encode(self.c.report())),self.c.ledger.MAX_BYTES)
    def test_256_count_ceiling_without_pruning_or_owner_reset(self):
        for i in range(162):
            q=request('look');q['owner_generation']=95+i;self.c.ledger.data['actions'][q['id']]=record(q)
        self.c.ledger.save();self.assertEqual(len(self.c.report()['actions']),256)
        with self.assertRaises(Refused):self.submit('look')
        self.assertEqual(len(self.c.report()['actions']),256);self.assertEqual(self.f.posts(),[])
        for aid,original in ORIGINAL['actions'].items():self.assertEqual(self.c.report(aid),original)
    def test_status_stop_routes_only_by_stored_original_profile(self):
        old_by_profile={r['request']['profile']:r for r in ORIGINAL['actions'].values()}
        for old in old_by_profile.values():
            before=len(self.f.calls)
            with patch.object(self.f,'request',return_value=RawReply(200,encode(old['terminal_native']))) as transport:
                aid=old['request']['id'];self.c.status(aid);self.c.stop(aid)
                expected='/control/recovery-short-input/v1/' if old['request']['profile']=='recovery_short_input_v1' else '/control/recovery-interaction/v1/'
                self.assertTrue(all(c.args[1].startswith(expected) for c in transport.call_args_list))
                self.assertEqual(transport.call_args_list[-1].args[2]['profile'],old['request']['profile'])
    def test_closed_original_not_erased_by_later_bad_status(self):
        q,_=self.submit('look');terminal=copy.deepcopy(self.c.report(q['id'])['terminal_native']);self.f.modify=lambda r:dict(r,owner_id=str(uuid4()));self.c.status(q['id'])
        self.assertEqual(self.c.report(q['id'])['state'],'CLOSED');self.assertEqual(self.c.report(q['id'])['terminal_native'],terminal)
    def test_no_new_owner_bootstrap_and_report_no_credentials(self):
        with self.assertRaises(Refused):Controller(Path(self.tmp.name)/'missing',self.f)
        self.c.close()
        with patch('interaction2_controller.__main__.getpass.getpass',side_effect=AssertionError('no token read')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--ledger',str(self.directory),'--endpoint',ENDPOINT,'report']),0)

if __name__=='__main__':unittest.main()
