"""Synthetic state machine fixtures; no queue, live game, UI or socket access."""
import unittest
from dataclasses import replace
from copy import deepcopy
from expedition_prerequisites import (Identity, Position, PearlIntent, UseObservation, TrajectoryProof,
    OneShotPearl, OneShotRegistry, ShulkerCycle, Stopped, cargo_slots, shulker_contents)


IDENTITY = Identity("s", "w", "p", "minecraft:the_end")
ORIGIN, LANDING = Position(0, 64, 0), Position(10, 64, 0)
INTENT = PearlIntent("action", "owner", IDENTITY, 4, 2, "minecraft:ender_pearl", 3, ORIGIN, LANDING, -90, 0)
OBS = UseObservation(IDENTITY, 4, "owner", ORIGIN, 2, "minecraft:ender_pearl", 3, 0, True, True, True)


class SyntheticVerifier:
    def verify(self, intent, observation, now_ms):
        return TrajectoryProof(intent, observation, now_ms, now_ms + 50, "offline-ray-target", True, True)


def empty():
    return {"empty": True, "id": "", "count": 0}


def cargo(count=10):
    return {"empty": False, "id": "minecraft:cobblestone", "count": count, "damage": 0,
            "identity_complete": True}


def slots(size=27, count=0):
    rows = [empty() for _ in range(size)]
    if count:
        rows[0] = cargo(count)
    return rows


class OneShotTest(unittest.TestCase):
    def action(self):
        return OneShotPearl(INTENT, 0, SyntheticVerifier())

    def test_default_verifier_never_launches(self):
        a = OneShotPearl(INTENT, 0)
        with self.assertRaisesRegex(Stopped, "not_implemented"):
            a.dispatch_proposal(OBS, 0)
        self.assertEqual(a.dispatches, 0)

    def test_single_use_spent_before_adapter_and_cannot_replay(self):
        a = self.action()
        self.assertEqual(a.dispatch_proposal(OBS, 1), "DISPATCH_ONCE")
        self.assertTrue(a.release_required)
        with self.assertRaisesRegex(Stopped, "no_replay"):
            a.dispatch_proposal(OBS, 2)
        a.stop("lost_result")
        self.assertEqual(a.phase, "uncertain")
        with self.assertRaisesRegex(Stopped, "no_replay"):
            a.dispatch_proposal(OBS, 3)
        self.assertEqual(a.dispatches, 1)

    def test_registry_deduplicates_cancelled_and_uncertain(self):
        r = OneShotRegistry(IDENTITY, "owner")
        a = r.begin(INTENT, 0, SyntheticVerifier())
        self.assertIs(a, r.begin(INTENT, 1))
        with self.assertRaisesRegex(Stopped, "busy"):
            r.begin(replace(INTENT, action_id="other"), 2)
        a.dispatch_proposal(OBS, 2)
        a.stop("response_lost")
        self.assertIs(a, r.begin(INTENT, 3))
        with self.assertRaisesRegex(Stopped, "payload_mismatch"):
            r.begin(replace(INTENT, expected_count=2), 4)
        with self.assertRaisesRegex(Stopped, "reconciliation_required"):
            r.begin(replace(INTENT, action_id="other"), 5)

    def test_registry_rejects_session_or_owner_changes(self):
        r = OneShotRegistry(IDENTITY, "owner")
        for i in (replace(INTENT, owner="other"), replace(INTENT, identity=replace(IDENTITY, session="new"))):
            with self.assertRaisesRegex(Stopped, "identity_changed"):
                r.begin(i, 0)

    def test_all_context_stops_are_terminal(self):
        for changed in (replace(OBS, alive=False), replace(OBS, connected=False), replace(OBS, screen_open=True),
                        replace(OBS, owner="other"), replace(OBS, identity=replace(IDENTITY, world="new"))):
            with self.subTest(changed=changed):
                a = self.action()
                with self.assertRaisesRegex(Stopped, "context_changed"):
                    a.dispatch_proposal(changed, 0)
                self.assertEqual(a.phase, "cancelled")
                self.assertEqual(a.dispatches, 0)

    def test_context_changes_after_dispatch_are_uncertain_and_release(self):
        a = self.action(); a.dispatch_proposal(OBS, 0)
        with self.assertRaises(Stopped):
            a.observe_landing(replace(OBS, connected=False), 1)
        self.assertEqual(a.phase, "uncertain"); self.assertTrue(a.release_required)

    def test_changed_stack_slot_cooldown_epoch_and_origin_rejected(self):
        for changed in (replace(OBS, slot=3), replace(OBS, count=2), replace(OBS, item_id="minecraft:egg"),
                        replace(OBS, epoch=5), replace(OBS, cooldown=True), replace(OBS, speed=.2),
                        replace(OBS, position=Position(.1,64,0)), replace(OBS, grounded=False),
                        replace(OBS, supported=False), replace(OBS, loaded=False)):
            a = self.action()
            with self.assertRaises(Stopped): a.dispatch_proposal(changed, 0)
            self.assertEqual(a.dispatches, 0)

    def test_budget_is_finite_before_and_after_launch(self):
        a = self.action()
        with self.assertRaisesRegex(Stopped, "deadline"):
            a.dispatch_proposal(OBS, 8000)
        self.assertEqual(a.phase,"cancelled")
        b = self.action(); b.dispatch_proposal(OBS, 0)
        with self.assertRaisesRegex(Stopped,"deadline"):
            b.observe_landing(OBS,8000)
        self.assertEqual(b.phase,"uncertain")

    def test_landing_needs_fresh_epoch_location_support_and_velocity(self):
        a=self.action(); a.dispatch_proposal(OBS,0)
        landed=replace(OBS,epoch=5,position=LANDING,count=2)
        for observation in (replace(landed,epoch=4), replace(landed,supported=False), replace(landed,speed=.2),
                            replace(landed,loaded=False), replace(landed,position=Position(11,64,0))):
            self.assertFalse(a.observe_landing(observation,1))
        self.assertTrue(a.observe_landing(landed,2))
        self.assertEqual(a.reason,"client_observed_not_server_confirmed")
        a.confirm_release(); self.assertFalse(a.release_required)

    def test_landing_cannot_use_another_hotbar_stack_as_consumption_evidence(self):
        a=self.action();a.dispatch_proposal(OBS,0)
        with self.assertRaisesRegex(Stopped,"held_slot_changed"):
            a.observe_landing(replace(OBS,epoch=5,position=LANDING,slot=8,count=2),1)
        self.assertEqual(a.phase,"uncertain")
        self.assertTrue(a.release_required)

    def test_observation_counts_epochs_slots_and_flags_are_strict(self):
        for change in ({"slot":True},{"count":True},{"epoch":1.5},{"loaded":1},{"grounded":"true"},
                       {"speed":float("nan")},{"count":0},{"item_id":False}):
            with self.assertRaises(Stopped):replace(OBS,**change)

    def test_stale_or_mismatched_proof_never_dispatches(self):
        class Bad:
            def __init__(self,change): self.change=change
            def verify(self,intent,obs,now):
                return replace(SyntheticVerifier().verify(intent,obs,now),**self.change)
        for change in ({"intent":replace(INTENT,action_id="other")},{"expires_ms":200},{"issued_ms":5},
                       {"ray_target":""},{"verified_loaded_sweep":False},{"verified_landing_region":False}):
            a=OneShotPearl(INTENT,0,Bad(change))
            with self.assertRaises(Stopped): a.dispatch_proposal(OBS,0)
            self.assertEqual(a.dispatches,0)

    def test_wire_like_parameters_have_strict_types_bounds_and_whitelist(self):
        for change in ({"slot":True},{"slot":9},{"epoch":False},{"budget_ms":10001},{"expected_count":17},
                       {"item_id":"minecraft:milk_bucket"},{"landing":Position(100,64,0)},
                       {"yaw":float("nan")},{"pitch":91},{"action_id":""}):
            with self.assertRaises(Stopped): replace(INTENT,**change)

    def test_clock_regression_rejected(self):
        a=self.action();a.dispatch_proposal(OBS,5)
        with self.assertRaisesRegex(Stopped,"clock_regressed"):a.observe_landing(OBS,4)


class ShulkerTest(unittest.TestCase):
    def cycle(self,before=0,after=10):
        return ShulkerCycle(IDENTITY,"owner",ORIGIN,slots(count=before),slots(count=after),0)

    def evidence(self,step,load=True):
        before, after=(0,10) if load else (10,0)
        values={
            "place":{"position":ORIGIN,"shulker_block":True},
            "open":{"position":ORIGIN,"menu_class":"net.minecraft.world.inventory.ShulkerBoxMenu","menu_id":7,
                    "cursor_empty":True,"slots":slots(count=before),"player_inventory":slots(36,10-before)},
            "transfer":{"menu_id":7,"cursor_empty":True,"slots":slots(count=after),"player_inventory":slots(36,10-after)},
            "close":{"screen_closed":True,"cursor_empty":True},
            "break":{"position":ORIGIN,"block_absent":True},
            "pickup":{"new_matching_boxes":1,"identity_complete":True,"slots":slots(count=after)},
            "replace":{"position":ORIGIN,"shulker_block":True},
            "reopen":{"position":ORIGIN,"menu_class":"net.minecraft.world.inventory.ShulkerBoxMenu","menu_id":8,
                      "cursor_empty":True,"slots":slots(count=after)},
            "verify":{"menu_id":8,"cursor_empty":True,"slots":slots(count=after)}}
        return dict(values[step],fresh=True)

    def advance(self,c,step,evidence=None,load=True):
        self.assertEqual(c.propose(step,IDENTITY,"owner",0),step)
        return c.confirm(step,IDENTITY,"owner",0,evidence or self.evidence(step,load))

    def test_complete_load_recover_and_replace_reopen_validation(self):
        c=self.cycle()
        for step in c.STEPS:self.advance(c,step)
        self.assertEqual(c.phase,"complete")
        with self.assertRaisesRegex(Stopped,"terminal"):c.propose("again",IDENTITY,"owner",1)

    def test_complete_unload_conserves_inventory(self):
        c=self.cycle(10,0)
        for step in c.STEPS:self.advance(c,step,load=False)
        self.assertEqual(c.phase,"complete")

    def test_pending_and_lost_results_are_not_replayed(self):
        c=self.cycle();c.propose("p",IDENTITY,"owner",0)
        with self.assertRaisesRegex(Stopped,"no_replay"):c.propose("new",IDENTITY,"owner",1)
        c.stop("lost")
        with self.assertRaises(Stopped):c.propose("new",IDENTITY,"owner",2)
        self.assertEqual(c.phase,"uncertain:lost")

    def test_id_mismatch_stale_confirmation_and_reuse_rejected(self):
        c=self.cycle();c.propose("p",IDENTITY,"owner",0)
        with self.assertRaisesRegex(Stopped,"unbound"):c.confirm("wrong",IDENTITY,"owner",0,{})
        with self.assertRaisesRegex(Stopped,"fresh"):c.confirm("p",IDENTITY,"owner",0,{})
        c.confirm("p",IDENTITY,"owner",0,self.evidence("place"))
        with self.assertRaisesRegex(Stopped,"reused"):c.propose("p",IDENTITY,"owner",0)

    def test_exact_27_slot_menu_and_complete_components_required(self):
        for rows in (slots(26),slots(28),[dict(cargo(),identity_complete=False)]+slots(26),
                     [dict(cargo(),id="minecraft:blue_shulker_box")]+slots(26)):
            with self.assertRaises(Stopped):cargo_slots(rows)

    def test_native_sparse_container_summary_requires_complete_bounded_identity(self):
        raw={"id":"minecraft:blue_shulker_box","count":1,"identity_complete":True,
             "container":{"schema_version":1,"capacity":27,"slots_truncated":False,
                          "nested_containers_supported":False,"slot_extent":27,"items":[dict(cargo(),slot=26)]}}
        expected=slots();expected[26]=cargo()
        self.assertEqual(shulker_contents(raw),cargo_slots(expected))
        bad=deepcopy(raw);bad["identity_complete"]=False
        with self.assertRaises(Stopped):shulker_contents(bad)
        for change in ({"slots_truncated":True},{"capacity":28},{"slot_extent":28},
                       {"items":[dict(cargo(),slot=27)]},{"items":[dict(cargo(),slot=1),dict(cargo(),slot=1)]},
                       {"items":[dict(cargo(),slot=0,identity_complete=False)]}):
            bad=deepcopy(raw);bad["container"].update(change)
            with self.assertRaises(Stopped):shulker_contents(bad)

    def test_menu_class_menu_id_cursor_and_target_must_match(self):
        for change in ({"menu_class":"net.minecraft.world.inventory.ChestMenu"},{"menu_id":0},
                       {"cursor_empty":False},{"position":LANDING},{"slots":slots(count=1)}):
            c=self.cycle();self.advance(c,"place")
            c.propose("open",IDENTITY,"owner",0)
            with self.assertRaises(Stopped):c.confirm("open",IDENTITY,"owner",0,dict(self.evidence("open"),**change))

    def test_transfer_checks_actual_inventory_conservation(self):
        c=self.cycle();self.advance(c,"place");self.advance(c,"open")
        c.propose("transfer",IDENTITY,"owner",0)
        bad=dict(self.evidence("transfer"),player_inventory=slots(36,10))
        with self.assertRaisesRegex(Stopped,"conservation_failed"):c.confirm("transfer",IDENTITY,"owner",0,bad)

    def test_pickup_not_equated_to_break_or_ambiguous_box(self):
        for change in ({"new_matching_boxes":0},{"new_matching_boxes":2},{"identity_complete":False},
                       {"slots":slots(count=9)}):
            c=self.cycle()
            for step in c.STEPS[:5]:self.advance(c,step)
            c.propose("pickup",IDENTITY,"owner",0)
            with self.assertRaises(Stopped):c.confirm("pickup",IDENTITY,"owner",0,dict(self.evidence("pickup"),**change))

    def test_context_and_deadline_stop(self):
        for identity,owner,now in ((replace(IDENTITY,world="new"),"owner",0),(IDENTITY,"other",0),(IDENTITY,"owner",30000)):
            c=self.cycle()
            with self.assertRaises(Stopped):c.propose("p",identity,owner,now)
            self.assertTrue(c.phase.startswith("stopped:"))

if __name__ == "__main__":unittest.main()
