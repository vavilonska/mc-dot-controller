"""Java-encoded production pure episode model, strict schema, and regression fences."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest
from resident_controller.fall_rescue_control import validate_status
from resident_controller.fall_rescue_status import BASE, EPISODE, FLAGS, BASIS
ROOT=Path(__file__).resolve().parents[2]
ROWS=json.loads((Path(__file__).parent/'fixtures/fall-rescue-java-model-status.json').read_text())
COMMAND={'op':'fall_rescue_control','operation':'status','arm_id':'a'*32,
    'control_owner':{'owner_id':'b'*32,'owner_generation':1,'job_id':'job'},
    'expected_context':{'action_session':'session','world_generation':'world','player_uuid':'player','dimension':'minecraft:overworld'},
    'expected_resident_session':'resident'}
class FallEvidenceTests(unittest.TestCase):
    def test_java_model_progression(self):
        previous=None
        for row in ROWS:
            previous=validate_status(row,COMMAND,previous)
        self.assertTrue(previous['last_episode']['rescue_confirmed'])
    def test_native_serializer_source_parity(self):
        source=(ROOT/'client-mod/src/main/java/io/github/campione01/mineclientbridge/NativeFallRescue.java').read_text()
        status=source.split('static JsonObject status(){',1)[1].split('private static JsonObject episodeStatus',1)[0]
        nativekeys=set(re.findall(r'j\.add(?:Property)?\("([^"]+)"',status))
        self.assertTrue(BASE <= nativekeys <= BASE|{'episode','last_episode','last_client_observation','superseded_callback_failure'})
        serializer=source.split('private static JsonObject episodeStatus',1)[1].split('static JsonObject capabilities()',1)[0]
        self.assertEqual(set(re.findall(r'j\.add(?:Property)?\("([^"]+)"',serializer)),EPISODE|{'interaction_result','interrupted_action'})
        self.assertIn(BASIS,serializer)
    def test_missing_or_extra_fields_and_bool_types(self):
        for source in ROWS:
            for key in BASE:
                row=deepcopy(source);del row[key]
                with self.subTest(key=key),self.assertRaises(ValueError):validate_status(row,COMMAND)
            row=deepcopy(source);row['extra']=1
            with self.assertRaises(ValueError):validate_status(row,COMMAND)
            for key in ('armed','input_owned','automation_blocked','no_auto_resume','unknown_outcome_quarantined'):
                row=deepcopy(source);row[key]=1
                with self.assertRaises(ValueError):validate_status(row,COMMAND)
        for key in EPISODE:
            row=deepcopy(ROWS[-1]);del row['last_episode'][key]
            with self.subTest(episode_key=key),self.assertRaises(ValueError):validate_status(row,COMMAND)
    def test_confirmed_requires_coherent_bound_server_evidence(self):
        for key in set(FLAGS)-{'client_prediction_water'}:
            row=deepcopy(ROWS[-1]);row['last_episode'][key]=False
            with self.subTest(key=key),self.assertRaises(ValueError):validate_status(row,COMMAND)
        for key,value in (('episode_id','foreign'),('confirmation_basis','client_prediction'),('outcome','success'),
                          ('baseline_server_tick',-1),('water_target',{'x':0,'y':64,'z':True})):
            row=deepcopy(ROWS[-1]);row['last_episode'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_status(row,COMMAND)
    def test_later_omission_or_regression_never_erases_attempt(self):
        previous=ROWS[3]
        for source in ROWS[:3]:
            with self.assertRaises(ValueError):validate_status(source,COMMAND,previous)
        for key in FLAGS:
            if not previous['episode'][key]:continue
            row=deepcopy(previous);row['episode'][key]=False
            with self.assertRaises(ValueError):validate_status(row,COMMAND,previous)
        for mutate in (lambda r:r.pop('episode'),lambda r:r.update(episodes_used=0),
                       lambda r:r['episode'].update(episode_id='foreign'),lambda r:r['episode'].update(age_ticks=1),
                       lambda r:r['episode'].update(water_target={'x':2,'y':64,'z':1})):
            row=deepcopy(previous);mutate(row)
            with self.assertRaises(ValueError):validate_status(row,COMMAND,previous)
        old=deepcopy(previous);old['arm_revision']=3
        with self.assertRaises(ValueError):validate_status(previous,COMMAND,old)
    def test_empty_present_episode_and_unreleased_automation_are_rejected(self):
        for key in ('episode','last_episode'):
            for empty in (None,{},False,[]):
                row=deepcopy(ROWS[0]);row[key]=empty
                with self.subTest(key=key,empty=empty),self.assertRaises(ValueError):validate_status(row,COMMAND)
        row=deepcopy(ROWS[-1]);row['automation_blocked']=True
        with self.assertRaises(ValueError):validate_status(row,{**COMMAND,'operation':'disarm'},ROWS[3])

    def test_native_empty_predecessor_is_not_takeover_authority(self):
        row=deepcopy(ROWS[-1]);row['last_episode']['interrupted_action']={}
        self.assertTrue(validate_status(row,COMMAND)['last_episode']['rescue_confirmed'])
        for previous in (None,[],{'action_id':'foreign'},{'action_id':'foreign','action':'follow_path',
                'effect_outcome':'unknown_interrupted','no_auto_resume':True,'requires_reconciliation_before_retry':True}):
            bad=deepcopy(row);bad['last_episode']['interrupted_action']=previous
            with self.assertRaises(ValueError):validate_status(bad,COMMAND)

    def test_old_superseded_diagnostic_is_display_only(self):
        row=deepcopy(ROWS[0]);row['superseded_callback_failure']={'schema_version':1,'arm_id':'old-arm',
            'episode_id':'old-arm:1','operation_revision':3,'reason':'fall_rescue_aim_owner_changed',
            'diagnostic_only':True,'original_outcome':'unknown_superseded_callback',
            'dispatch_attempted':True,'replacement_touched':False}
        self.assertEqual(validate_status(row,COMMAND)['episodes_used'],0)
        for key,value in (('diagnostic_only',False),('replacement_touched',True),('episode_id','foreign:1'),
                          ('original_outcome','succeeded'),('operation_revision',True)):
            bad=deepcopy(row);bad['superseded_callback_failure'][key]=value
            with self.assertRaises(ValueError):validate_status(bad,COMMAND)
        # Diagnostic evidence can never replace a missing current episode.
        bad=deepcopy(row);bad['episodes_used']=1
        with self.assertRaises(ValueError):validate_status(bad,COMMAND)

    def test_disarm_and_renew_have_exact_revision_and_evidence(self):
        disarm={**COMMAND,'operation':'disarm'}
        self.assertTrue(validate_status(ROWS[-1],disarm,ROWS[3])['last_episode']['rescue_confirmed'])
        with self.assertRaises(ValueError):validate_status(ROWS[0],disarm,ROWS[3])
        renew={**COMMAND,'operation':'renew','ttl_ms':5000,'expected_arm_revision':1}
        good=deepcopy(ROWS[3]);good['arm_revision']=2
        self.assertEqual(validate_status(good,renew,ROWS[3])['arm_revision'],2)
        good['episode']['dispatch_attempted']=False
        with self.assertRaises(ValueError):validate_status(good,renew,ROWS[3])

if __name__=='__main__':unittest.main()
