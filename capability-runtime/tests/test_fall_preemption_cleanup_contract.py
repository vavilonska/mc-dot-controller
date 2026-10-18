"""Exact production seam parity and native-produced registry/HTTP evidence."""
from pathlib import Path
import json,unittest,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from resident_controller.transport import Bridge
from resident_controller import fall_rescue_attached as attached
import test_attached_fall_boundaries as boundaries
ROOT=Path(__file__).resolve().parents[2]
JAVA=ROOT/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
class PreemptionCleanupContractTests(unittest.TestCase):
 def test_scope_surrounds_only_exact_old_finish_and_is_always_closed(self):
  text=(JAVA/'ClientActions.java').read_text();section=text.split('static JsonObject preemptForFallRescue(',1)[1].split('private static boolean context(',1)[0]
  self.assertIn('FALL_CLEANUP.open(old,old.scopedCombat,old.entry',section)
  self.assertIn('active==null&&ACTIONS.active()==old.entry&&ownershipRevision==cleanupRevision',section)
  self.assertIn('&&old.player==mc.player&&old.level==mc.level&&preemptionChannelsAbsent()&&successorBound.getAsBoolean()',section)
  self.assertIn('try {finish("cancelled","native_fall_rescue_preempted");}',section)
  self.assertIn('finally {FALL_CLEANUP.close(scope);}',section)
  self.assertIn('old.scopedCombat.markFallPreempted()',section)
  self.assertGreaterEqual(section.count('requirePreemptionSuccessor(mc,old,successorBound);'),2)
 def test_foreign_raw_and_guarded_channels_are_refused_without_global_release(self):
  section=(JAVA/'ClientActions.java').read_text().split('static JsonObject preemptForFallRescue(',1)[1].split('private static boolean context(',1)[0]
  self.assertNotIn('BridgeServer.releaseAllInputs()',section)
  self.assertNotIn('releaseUsingItem(',section)
  self.assertNotIn('GuardedGameMovement.cancelOnGameThread',section)
  self.assertEqual(section.count('requirePreemptionChannelsAbsent();'),2)
  for value in ('BridgeServer.hasHeldInputs()', 'ClientInputIsolation.statistics().heldKeys()', 'GuardedGameMovement.LEASES.status().ownerRequestId()', 'fall_rescue_foreign_input_channel_present'):
   self.assertIn(value,section)
  self.assertIn('if(active!=null||(old!=null&&(old.player!=mc.player||old.level!=mc.level))',section)
  self.assertIn('||!preemptionChannelsAbsent()||!bound.getAsBoolean())',section)
 def test_native_successor_binding_is_complete_and_no_new_authority(self):
  text=(JAVA/'NativeFallRescue.java').read_text();section=text.split('Object cleanupGameMode=mc.gameMode;',1)[1].split('var inventory=',1)[0]
  for value in ('sameContext(tickAuthorization,operation,e,authorization,OPERATIONS.stamp(),current)','owns(e)',
    'mc.player==e.player','mc.level==e.level','mc.gameMode==cleanupGameMode','mc.screen==null',
    'tickAuthorization.session().equals(ClientActions.session())','WorldGeneration.matches(e.level,tickAuthorization.world())',
    'System.nanoTime()<deadline','!e.proof.timedOut(tick)','!e.preemptionVerified','!e.proof.attempted()'):
   self.assertIn(value,section)
 def test_cleanup_final_fence_follows_getters(self):
  text=(JAVA/'ScopedCombat.java').read_text().split('void cleanupFence(',1)[1].split('void chargeEffect',1)[0]
  self.assertEqual(text.count('ClientActions.terminalCombatCleanup(this,entry)'),2)
  self.assertLess(text.index('player.isUsingItem()'),text.rindex('ClientActions.terminalCombatCleanup(this,entry)'))
  self.assertIn('actionSession.equals(ClientActions.session())&&WorldGeneration.matches(level,world)',text)
 def test_cleanup_does_not_authorize_effect_dispatch(self):
  text=(JAVA/'ScopedCombatDispatch.java').read_text()
  self.assertNotIn('terminalCombatCleanup',text.split('private static <T> T run(',1)[1].split('static void cleanup(',1)[0])
  self.assertIn('ServerboundPlayerActionPacket.Action.RELEASE_USE_ITEM',text)
  self.assertIn('scoped_combat_cleanup_nonrelease_packet',text)
 def test_final_original_registry_is_not_replacement(self):
  text=(JAVA/'ClientActions.java').read_text().split('if(FALL_CLEANUP.active()) {',1)[1].split('ACTIONS.finishAfterCleanup',1)[0]
  self.assertIn('FALL_CLEANUP.bound(a,a.entry)',text)
  self.assertIn('if(ACTIONS.active()!=a.entry){a.entry.result.addProperty("unknown_outcome",true);return;}',text)
 def test_pose_callback_fence_precedes_original_input_zero(self):
  text=(JAVA/'ClientActions.java').read_text().split('private static void finish(String status, String reason)',1)[1]
  before=text.split('a.input.forwardImpulse =',1)[0]
  self.assertGreater(before.rindex('requireCleanupOwner(a);'),before.index('a.player.getZ()'))
  self.assertIn('if(ACTIONS.active()==old.entry)ACTIONS.finishAfterCleanup', (JAVA/'ClientActions.java').read_text())
 def test_sprint_and_shield_release_steps_are_fenced(self):
  sprint=(JAVA/'ClientActions.java').read_text().split('private static void sprint(',1)[1].split('private static void recoverEnvironment',1)[0]
  self.assertIn('down->{requireCleanupOwner(a);mc.options.keySprint.setDown(down);}',sprint)
  self.assertIn('requireCleanupOwner(a);a.player.setSprinting(false);',sprint)
  shield=(JAVA/'BoundedCombat.java').read_text().split('private void releaseShield(',1)[1].split('private void scopedRawOwner',1)[0]
  self.assertIn('if(scopedGuard!=null){',shield);self.assertNotIn('request.defensive()',shield)
  self.assertGreaterEqual(shield.count('ScopedCombatDispatch.cleanupStep(scopedGuard);'),4)
 def test_permanent_preempted_guard_has_no_ordinary_cleanup_fallback(self):
  text=(JAVA/'ClientActions.java').read_text().split('static boolean terminalCombatCleanup(',1)[1].split('static JsonObject preemptForFallRescue',1)[0]
  self.assertIn('FALL_CLEANUP.active()||guard!=null&&guard.fallPreempted()',text)
  self.assertIn('?FALL_CLEANUP.permits(guard,entry):!ownsInput()',text)
 def test_actual_registry_codec_keeps_unknown_effects_and_release_truth(self):
  rows=json.loads((Path(__file__).parent/'fixtures/fall-preemption-cleanup-java-http.json').read_text())
  self.assertEqual(len(rows),2)
  for row in rows:
   value=json.loads(row['body']);self.assertEqual(row['http_status'],200)
   self.assertEqual(value['protocol'],'mineclient-bridge');self.assertEqual(value['schema_version'],2)
   self.assertEqual(value['status'],'cancelled' if row['scope_live'] else 'failed')
   self.assertIs(value['result']['input_release_confirmed'],row['scope_live'])
   self.assertIs(value['result']['unknown_outcome'],True)
   self.assertIs(value['result']['preempted_by_native_fall_rescue'],True)
   self.assertIs(value['result']['no_auto_resume'],True)
   self.assertIs(value['result']['requires_handoff'],True)
 def test_actual_http_registry_receipt_passes_only_strict_released_original_seal(self):
  rows=json.loads((Path(__file__).parent/'fixtures/fall-preemption-cleanup-java-http.json').read_text())
  payload=[b'']
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    self.send_response(200);self.send_header('Content-Length',str(len(payload[0])));self.end_headers();self.wfile.write(payload[0])
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  bridge=Bridge('http://127.0.0.1:'+str(server.server_port),'synthetic-test-only')
  try:
   for row in rows:
    b=boundaries.Boundaries();b.setUp();payload[0]=row['body'].encode()
    action=bridge.request('GET','/control/action/status?action_id='+b.binding['action_id'])
    b.command['expected_action_session']=action['action_session'];b.binding=attached.binding_for(b.command,'request-one',boundaries.SESSION)
    b.task.fall_rescue={'binding':b.binding};b.task.last_action_result=action
    state=b.status(4);state['action_session']=action['action_session']
    seal=attached.seal(b.task,state)
    if row['scope_live']:self.assertEqual(attached.verify_seal(seal,b.command,'request-one',boundaries.SESSION),seal)
    else:
     with self.assertRaises(ValueError):attached.verify_seal(seal,b.command,'request-one',boundaries.SESSION)
  finally:server.shutdown();server.server_close();thread.join(2)
if __name__=='__main__':unittest.main()
