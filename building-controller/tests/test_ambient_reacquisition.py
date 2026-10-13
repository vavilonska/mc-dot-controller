"""Availability is never safety: only exact missing-server-row facts may wait."""
from copy import deepcopy
import unittest
from building_controller.ambient_entities import classify_ambient_entities, reacquirable_entity_absence
from tests.test_ambient_entities import sample, policy, entity, CONTEXT


def absent(kind='bee', **kwargs):
    row=entity(kind, **kwargs)
    keys=('schema_version','entity_uuid','entity_id','entity_type','dimension',
          'world_generation','player_uuid','coverage_complete','inspected')
    facts={k:row['native_living'][k] for k in keys}
    facts.update(known=False,source='unavailable',reason='entity_not_observed',current_target_known=False)
    row['native_living']=facts
    return row


class AmbientReacquisitionTests(unittest.TestCase):
    def test_exact_absence_is_rejected_but_may_request_a_new_read_without_changing_raw(self):
        state=sample([absent(),entity('sheep',ident=12),entity('boat',ident=13)])
        before=deepcopy(state); report=classify_ambient_entities(state,policy())
        self.assertFalse(report.ok)
        evidence=reacquirable_entity_absence(state,policy())
        self.assertEqual(evidence['context'],list(CONTEXT))
        self.assertEqual(evidence['missing_entities'][0]['reason'],'entity_not_observed')
        self.assertIs(evidence['observation_accepted'],False)
        self.assertEqual(state,before)
        self.assertEqual(classify_ambient_entities(state,policy()),report)
    def test_disappearance_or_calm_return_requires_separate_complete_fresh_state(self):
        self.assertFalse(classify_ambient_entities(sample([absent()]),policy()).ok)
        for rows in ([],[entity()]):
            state=sample(rows)
            self.assertTrue(classify_ambient_entities(state,policy()).ok)
            self.assertIsNone(reacquirable_entity_absence(state,policy()))
    def test_persistent_missing_stays_rejected(self):
        state=sample([absent()])
        for _ in range(3):
            self.assertFalse(classify_ambient_entities(state,policy()).ok)
            self.assertIsNotNone(reacquirable_entity_absence(state,policy()))
    def test_mismatch_and_ambiguous_unavailable_shapes_never_qualify(self):
        changes=[lambda f:f.update(entity_id=99),lambda f:f.update(entity_uuid=CONTEXT[2]),
            lambda f:f.update(world_generation=CONTEXT[2]),lambda f:f.update(player_uuid=CONTEXT[0]),
            lambda f:f.update(dimension='minecraft:the_end'),lambda f:f.update(entity_type='minecraft:sheep'),
            lambda f:f.update(source='integrated_server_tick'),lambda f:f.update(reason='capture_expired'),
            lambda f:f.update(known=True),lambda f:f.update(current_target_known=True),
            lambda f:f.update(coverage_complete=False),lambda f:f.update(inspected=0),
            lambda f:f.update(inspected=True),lambda f:f.update(schema_version=True),
            lambda f:f.update(current_target=None),lambda f:f.update(aggressive=False),
            lambda f:f.update(aggressive=True),lambda f:f.pop('known')]
        for change in changes:
            row=absent();change(row['native_living'])
            with self.subTest(facts=row['native_living']):
                self.assertIsNone(reacquirable_entity_absence(sample([row]),policy()))
    def test_known_stale_and_angry_facts_never_qualify(self):
        for field,value in [('sample_age_ms',251),('aggressive',True),('current_target',{'uuid':CONTEXT[2]})]:
            row=entity();row['native_living'][field]=value
            self.assertIsNone(reacquirable_entity_absence(sample([row]),policy()))
    def test_complete_scan_and_all_other_rows_must_be_safe(self):
        for change in (lambda s:s['nearby'].update(truncated=True),
                       lambda s:s['nearby'].update(total=2),
                       lambda s:s['nearby'].update(radius=20),
                       lambda s:s.update(private_singleplayer=False)):
            state=sample([absent()]);change(state)
            self.assertIsNone(reacquirable_entity_absence(state,policy()))
        other=entity('sheep',ident=12);other['native_living']['aggressive']=True
        self.assertIsNone(reacquirable_entity_absence(sample([absent(),other]),policy()))
    def test_no_wait_for_nearby_or_invalid_body_or_motion(self):
        for row in (absent(x=15),absent('sheep',x=11)):
            self.assertIsNone(reacquirable_entity_absence(sample([row]),policy()))
        for change in (lambda r:r.update(health=0),lambda r:r.update(alive=False),
                       lambda r:r.update(velocity={'x':10.,'y':0.,'z':0.}),lambda r:r.pop('bounding_box')):
            row=absent();change(row)
            self.assertIsNone(reacquirable_entity_absence(sample([row]),policy()))
    def test_multiple_missing_distant_rows_remain_explicit_and_strict(self):
        state=sample([absent(),absent('sheep',ident=12)])
        evidence=reacquirable_entity_absence(state,policy())
        self.assertEqual(len(evidence['missing_entities']),2)
        self.assertFalse(classify_ambient_entities(state,policy()).ok)

if __name__=='__main__':unittest.main()
