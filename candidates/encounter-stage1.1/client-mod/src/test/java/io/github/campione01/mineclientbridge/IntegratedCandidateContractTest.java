package io.github.campione01.mineclientbridge;
import java.nio.file.*;
import com.google.gson.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
/** Cross-branch source/wire contracts. These do not execute a real Minecraft client. */
class IntegratedCandidateContractTest {
 static String src(String name)throws Exception{return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge",name));}
 @Test void nativeOwnerRemainsExclusiveAcrossBoatAndCombat()throws Exception{
  String a=src("ClientActions.java");
  assertTrue(a.indexOf("if (active != null) throw")<a.indexOf("new BoundedBoatDrive"));
  assertTrue(a.contains("new BoundedCombat"));assertTrue(a.contains("new BoundedBoatDrive"));
  assertTrue(a.contains("request.action().equals(\"combat_entity\")"));assertTrue(a.contains("request.action().equals(\"boat_drive\")"));
  assertFalse(src("ClientActionRequest.java").contains("draft_plan"));
 }
 @Test void boatKeepsOwnMotionPolicyAndDoesNotRelaxLandGuard()throws Exception{
  String n=src("NavigationPositionGuard.java"),a=src("ClientActions.java");
  assertTrue(n.contains("case \"follow_path\", \"break_block\", \"place_block\", \"combat_entity\" -> true"));
  assertFalse(n.contains("\"boat_drive\" -> true"));
  assertTrue(a.contains("NavigationPositionGuard.applies(active.entry.request.action())"));
  assertTrue(a.indexOf("NavigationPositionGuard.tick(mc)")<a.indexOf("if (!context(mc,\"pre_tick\")) return;"));
  assertTrue(a.contains("if (a.boat == null) input.left = input.right = false"));
  assertTrue(src("BoundedBoatDrive.java").contains("hasChunkAt"));
 }
 @Test void worldPlayerSessionAndNavigationBindingsPrecedeInputOwnership()throws Exception{
  String a=src("ClientActions.java");int owner=a.indexOf("active = new RuntimeAction");
  for(String s:new String[]{"NavigationPositionGuard.requireBinding(mc, request)","action_world_changed","action_session_changed","action_player_changed"})assertTrue(a.indexOf(s)>=0&&a.indexOf(s)<owner,s);
  String b=src("BridgeServer.java");assertTrue(b.contains("ClientActions.cancelId(id, expectedSession)"));
  int guard=a.indexOf("!ACTIONS.session.equals(expectedSession)");assertTrue(guard>=0&&guard<a.indexOf("return cancelId(id)",guard));
 }
 @Test void combatBindingsSurviveRequestParsing() {
  JsonObject b=JsonParser.parseString("{\"action_id\":\"c\",\"action\":\"combat_entity\",\"timeout_ms\":1000,\"expected_world_generation\":\"00000000-0000-0000-0000-000000000001\",\"expected_player_uuid\":\"00000000-0000-0000-0000-000000000002\",\"expected_action_session\":\"00000000-0000-0000-0000-000000000003\",\"target_uuid\":\"00000000-0000-0000-0000-000000000004\",\"target_entity_id\":1,\"target_type\":\"minecraft:zombie\",\"expected_navigation_epoch\":9,\"expected_origin\":{\"x\":1,\"y\":64,\"z\":2}}").getAsJsonObject();
  assertEquals(b,ClientActionRequest.parse(b).original());
 }
 @Test void cleanupStillIncludesBothOwnersAndEveryOuterTermination()throws Exception{
  String a=src("ClientActions.java");for(String s:new String[]{"a.boat.release", "a.combat.release", "deadline_exceeded", "world_transition", "player_unavailable", "screen_opened", "direct_takeover", "cancel_requested", "ACTIONS.finishAfterCleanup"})assertTrue(a.contains(s),s);
  assertTrue(src("BoundedBoatDrive.java").contains("boat_settled"));
 }
 @Test void branchCapabilitiesRetainedTogether()throws Exception{
  String b=src("BridgeServer.java");for(String s:new String[]{"ClientActionRequest.ACTIONS","BoundedContainerSnapshot.append", "navigation_guard"})assertTrue(b.contains(s),s);
  assertTrue(src("BoundedCombat.java").contains("CombatThreats"));assertTrue(src("BoundedCombat.java").contains("CombatDetour"));
  String at=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/resources/META-INF/accesstransformer.cfg"));assertTrue(at.contains("Boat"));assertTrue(at.contains("Minecraft"));
 }
}
