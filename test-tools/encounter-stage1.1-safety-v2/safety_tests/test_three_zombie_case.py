"""Three-target production ledger/runner/closeout with synthetic native receipts.

No transport construction or actual game. All evidence is written to temporary
ledgers; historical two-zombie files are left untouched.
"""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import test_active_case as active
import test_post_trial_safety as support
import test_operator_closeout as closeout
from encounter_binding import EncounterBinding, summarize
from encounter_contract import MODE, THREE_MODE
from post_trial_safety import PostTrialSafety, SafetyHalt, PAUSE_SCREEN
from active_case import run_registered_three_zombie_case
from fixtures_support import RESIDENT

NATIVE={x['name']:x for x in json.loads((Path(__file__).resolve().parents[1]/'fixtures/three-zombie-native-emitted-receipts.json').read_text())['cases']}
ORIGINAL_SAMPLE=support.sample

def setup_three(case='succeeded',request_id='synthetic_encounter_1'):
    data=copy.deepcopy(NATIVE[case]);request=data['request'];request.pop('action_id')
    b=EncounterBinding(request_id,RESIDENT,request['expected_action_session'],request['expected_world_generation'],request['expected_player_uuid'],'combat_entity',encounter_request=request)
    native=data['receipt'];native['action_id']=b.expected_action_id
    return b,native

def exact_sample(binding,native=None):
    value=ORIGINAL_SAMPLE(binding,native);count=len(value['state']['nearby']['entities'])
    value['state']['nearby'].update(total=count,returned=count);return value

class ThreeActiveCaseTests(active.ActiveCaseTests):
    """Rerun every active-runner invariant with three real native fixture identities."""
    def setUp(self):
        super().setUp()
        self.addCleanup(patch.stopall)
        patch.object(support,'sample',exact_sample).start()
        patch.object(active,'setup',setup_three).start()
        h=self.h;h.b,h.native=setup_three()
        request=h.b.encounter_request;request['encounter_pause_on_terminal']=True
        h.b=EncounterBinding(h.b.request_id,h.b.resident_session,h.b.action_session,h.b.world_generation,h.b.player_uuid,h.b.action_kind,encounter_request=request)
        h.native=active.opt_in_native(h.native)
        h.o.resident=h.b.resident_session;h.o.session=h.b.action_session;h.o.world=h.b.world_generation;h.o.player=h.b.player_uuid
        self.q=active.ActiveQueue(h.b,h.native,h.o.out/'active.json');h.o.c=self.q
        h.s=PostTrialSafety(h.o,h.base/'shared-ledger');h.es=support.entities(h.b)
        self.q.current['state'].update(paused=True,screen_open=True);self.q.current['screen']={'open':True,'class':PAUSE_SCREEN}
        self.proof={'entities':[{'uuid':e['uuid'],'no_ai':False,'is_baby':False,'evidence_ref':'synthetic-three-ai-proof'} for e in h.es]}
    def register(self,**changes):
        return super().register(**dict({'encounter_mode':THREE_MODE},**changes))
    def run_case(self):
        self.register()
        return run_registered_three_zombie_case(self.h.s,self.h.b,'active',resume_authorization_ref='synthetic-explicit-resume-approval')
    def test_old_default_registration_does_not_infer_three(self):
        with self.assertRaisesRegex(SafetyHalt,'exactly_two'):
            self.register(encounter_mode=MODE)
        self.assertEqual(self.q.mutations(),[])
    def test_exact_third_registration_proof_and_current_identity_required(self):
        proof=copy.deepcopy(self.proof);proof['entities'].pop()
        with self.assertRaisesRegex(SafetyHalt,'proof_required'):self.register(active_ai_proof=proof)
        es=copy.deepcopy(self.h.es);es[2]['uuid']=es[0]['uuid']
        with self.assertRaisesRegex(SafetyHalt,'duplicate'):self.register(entities=es)
        self.q.current['state']['nearby']['entities'][2]['alive']=False
        with self.assertRaisesRegex(SafetyHalt,'unverified'):self.register()
        self.assertEqual(self.q.mutations(),[])
    def test_registration_stores_mode_and_scope_but_not_generic_allowlist(self):
        registered=self.register();self.assertEqual(registered['encounter_mode'],THREE_MODE)
        self.assertEqual(len(registered['entities']),3)
        with self.assertRaises(SafetyHalt):self.h.s.register_noai_case('not-noai',self.h.es,self.q.current,evidence_ref='synthetic',noai_proof=self.proof,authorization_ref='synthetic')
    def test_projectile_failure_stops_once_and_never_claims_clearance(self):
        for name in ['projectile','projectile_unknown']:
            # Only one trial per ledger: individual receipt binding checks are read-only.
            _,native=setup_three(name);native['action_session']=self.h.b.action_session;native['action_id']=self.h.b.expected_action_id
            native=active.opt_in_native(native)
            self.assertIsNone(self.h.b.native_problem(native))
            self.assertIsNone(native['result']['combat']['encounter']['outcome_scope'])
        _,native=setup_three('projectile');native['action_session']=self.h.b.action_session;native['action_id']=self.h.b.expected_action_id
        self.h.native=self.q.native=active.opt_in_native(native)
        self.q.main_response=active.receipt(self.h.b,self.h.native)
        result=self.run_case()
        self.assertEqual([v for v in self.ops() if v!='observe'],['direct','action'])
        self.assertEqual(result['resolution']['resolved_outcome']['native_action']['reason'],'encounter_projectile_observed_risk_remaining')
        self.assertFalse(result['live_acceptance_proven'])

class ThreeOperatorCloseoutTests(closeout.OperatorCloseoutTests):
    """Rerun the complete append-only closeout suite with an exact third target."""
    def setUp(self):
        with patch.object(active,'ActiveCaseTests',ThreeActiveCaseTests):
            super().setUp()
    def next_case(self,*,active_case=True):
        second,args=super().next_case(active_case=active_case)
        if active_case:
            args['encounter_mode']=THREE_MODE
        else:
            # A following old NoAI case remains exactly two, with no extra live zombie.
            removed=args['entities'].pop();args['noai_proof']['entities'].pop()
            obs=args['observation'];items=[x for x in obs['state']['nearby']['entities'] if x['uuid']!=removed['uuid']]
            obs['state']['nearby'].update(entities=items,total=len(items),returned=len(items))
            self.q.current=copy.deepcopy(obs)
        return second,args
    def test_two_deaths_cannot_close_three_scope_or_allow_next_case(self):
        proof=copy.deepcopy(self.proof);proof['cleanups'].pop()
        self.assert_refuses_proof(proof)
        second,args=self.next_case()
        with self.assertRaises(SafetyHalt):second.register_active_case(**args)
        self.assert_original_unchanged()
    def test_third_unknown_dispatch_absence_or_reused_proof_does_not_count_as_death(self):
        for kind in ['unknown','absent','duplicate']:
            proof=copy.deepcopy(self.proof)
            if kind=='unknown':proof['cleanups'][2]['dispatch']['receipt']['receipt']['post_uncertain']=True
            if kind=='duplicate':proof['cleanups'][2]=copy.deepcopy(proof['cleanups'][1])
            if kind=='absent':
                nearby=proof['cleanups'][2]['effect']['receipt']['receipt']['result']['state']['nearby']
                nearby['entities'].pop();nearby.update(total=2,returned=2)
            self.assert_refuses_proof(proof)
    def test_three_exact_deaths_are_read_only_append_only_evidence(self):
        self.assertEqual(len(self.proof['cleanups']),3);result=self.close()
        self.assertTrue(result['operator_closeout_verified']);self.assert_original_unchanged()
        self.assertEqual(self.q.mutations(),[])
        self.assertFalse(result['live_acceptance_proven'])
