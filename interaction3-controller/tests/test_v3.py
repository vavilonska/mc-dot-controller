"""New-profile-only diagnostics; old records remain byte-semantic originals."""
import copy
from pathlib import Path
import tempfile
import unittest
from interaction3_controller.controller import Controller
from interaction3_controller.legacy import V2Controller,Refused,encode,strict_json,PROFILE
from interaction3_controller.schema import receipt_valid,request_valid,payload_digest,refusal_valid
from support import clone,Fake,request,receipt,ORIGINAL,PLAN

class V3Tests(unittest.TestCase):
    def test_actual97_all_original_reader_request_terminal_and_encoded_equal(self):
        self.assertEqual(len(ORIGINAL['actions']),97)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);before=(p/'ledger.json').read_bytes()
            with Controller(p,Fake()) as c:
                for aid,old in ORIGINAL['actions'].items():
                    V2Controller.validate_request(old['request']);V2Controller._validate_receipt(old['terminal_native'],old['request'])
                    self.assertEqual(encode(c.report(aid)),encode(old))
                self.assertEqual(encode(c.report()),encode(ORIGINAL))
            self.assertEqual((p/'ledger.json').read_bytes(),before)
    def test_explicit_profile_digest_and_no_legacy_new_submission(self):
        q=request('look');v2=dict(q,profile='recovery_interaction_v2')
        self.assertNotEqual(payload_digest(q),payload_digest(v2))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);f=Fake()
            with Controller(p,f,PLAN) as c:
                c.observe()
                with self.assertRaises(Refused):c.start(v2)
                self.assertEqual(f.posts(),[])
    def test_closed_diagnostic_nullable_stage_and_int_bounds(self):
        refusal_valid(None)
        for stage in ('admit','first_interaction_tick','first_input'):
            for age,tick,mask in ((-1,0,0),(1000000001,0,1),(1,-1,3),(1,21,7),(1,1,15),(1,1,31),(1,1,63),(1,1,127)):
                refusal_valid(dict(stage=stage,age_ns=age,tick_delta=tick,predicate_mask=mask))
        for mask in (-1,-2):refusal_valid(dict(stage='admit',age_ns=None,tick_delta=None,predicate_mask=mask))
        base=dict(stage='admit',age_ns=1,tick_delta=1,predicate_mask=63)
        for change in ({'stage':'other'},{'age_ns':True},{'age_ns':2**63},{'tick_delta':-2**63-1},{'predicate_mask':255},{'predicate_mask':True},{'predicate_mask':2},{'age_ns':None},{'tick_delta':None},{'age_ns':None,'tick_delta':None,'predicate_mask':63},{'age_ns':None,'tick_delta':None,'predicate_mask':-1,'stage':'first_input'},{'extra':1}):
            with self.assertRaises(Refused):refusal_valid(dict(base,**change))
        with self.assertRaises(Refused):refusal_valid(base,observe=True)
        refusal_valid(dict(base,stage='observe'),observe=True)
    def test_diagnostic_does_not_relax_original_terminal_or_unknown(self):
        q=request('look');r=receipt(q,count=0);r['observation_refusal']=dict(stage='first_interaction_tick',age_ns=1000000001,tick_delta=1,predicate_mask=1);receipt_valid(r,q)
        for change in ({'release_proven':False},{'input_invalidated':False},{'payload_digest':'0'*64}):
            with self.assertRaises(Refused):receipt_valid(dict(r,**change),q)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);f=Fake();f.fail=True
            with Controller(p,f,PLAN) as c:
                c.observe();c.start(q);f.fail=False;f.modify=lambda value:dict(value,observation_refusal=r['observation_refusal'])
                self.assertEqual(c.status(q['id'])['state'],'UNKNOWN');self.assertTrue(c.report()['unknown_lock'])
    def test_diag_missing_and_extra_refuse_before_local_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);f=Fake()
            with Controller(p,f,PLAN) as c:
                f.obs.pop('observation_refusal')
                with self.assertRaises(Refused):c.observe()
                f.obs['observation_refusal']=dict(stage='observe',age_ns=None,tick_delta=None,predicate_mask=-1)
                with self.assertRaises(Refused):c.observe()
                self.assertEqual(f.posts(),[])

    def test_bad_new_diag_is_raw_evidence_unknown_not_reissued(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);f=Fake();q=request('look')
            f.modify=lambda r:dict(r,observation_refusal=dict(stage='admit',age_ns=1,tick_delta=1,predicate_mask=255))
            with Controller(p,f,PLAN) as c:
                c.observe();r=c.start(q);self.assertEqual(r['state'],'UNKNOWN')
                raw=strict_json(base64.b64decode(r['evidence'][0]['raw_base64']));self.assertEqual(raw['observation_refusal']['predicate_mask'],255)
                c.start(q);self.assertEqual(len(f.posts()),1)

    def test_diagnostic_effect_and_readiness_consistency_without_rejecting_queued(self):
        q=request('look');d=dict(stage='first_interaction_tick',age_ns=1000000001,tick_delta=1,predicate_mask=1)
        r=receipt(q,state='QUEUED');r['observation_refusal']=d;receipt_valid(r,q)
        r=receipt(q,count=1);r['observation_refusal']=d
        with self.assertRaises(Refused):receipt_valid(r,q)
        r=receipt(q,count=0);r['observation_refusal']=dict(d,stage='first_input')
        with self.assertRaises(Refused):receipt_valid(r,q)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger';clone(p);f=Fake();f.obs['observation_refusal']=dict(d,stage='observe')
            with Controller(p,f,PLAN) as c:
                with self.assertRaises(Refused):c.observe()
                f.obs.update(ready=False,reason='observation_context_changed');c.observe()
                f.obs['reason']='not_in_world'
                with self.assertRaises(Refused):c.observe()

    def test_known_stale_terminal_requires_diagnostic_unknown_does_not(self):
        q=request('look');r=receipt(q,count=0);r['reason']='observation_stale_or_moved'
        with self.assertRaises(Refused):receipt_valid(r,q)
        r=receipt(q,state='UNKNOWN',count=0);r['reason']='observation_stale_or_moved';receipt_valid(r,q)
