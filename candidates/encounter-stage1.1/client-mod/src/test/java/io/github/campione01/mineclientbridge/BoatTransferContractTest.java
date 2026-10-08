package io.github.campione01.mineclientbridge;

import java.nio.file.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Source wiring only; these checks do not run Minecraft. */
class BoatTransferContractTest {
    static String source(String name)throws Exception{return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge",name));}
    @Test void oneOrdinaryUseNoFallbackOrForcedMembership()throws Exception {String s=source("BoundedBoatTransfer.java");assertEquals(1,s.split("mc.gameMode.interact\\(",-1).length-1);assertTrue(s.indexOf("progress.dispatch(tick)")<s.indexOf("mc.gameMode.interact("));assertTrue(s.contains("ClientHooks.onClickInput"));for(String bad:new String[]{"interactAt(","startRiding(","stopRiding(","setPos(","setDeltaMovement(","createInteractionPacket","keyShift.setDown","keyUse.setDown"})assertFalse(s.contains(bad),bad);}
    @Test void exactPickReachAndIdentityCheckedOnClientThreadBeforeUse()throws Exception {String s=source("BoundedBoatTransfer.java");for(String required:new String[]{"mc.gameRenderer.pick(1.0F)","hit.getEntity() == boat","player.canInteractWithEntity(boat, 0.0)","player.hasLineOfSight(boat)","player.entityInteractionRange()","request.binding(","mc.level.getEntity(request.vehicleId()) != boat","boat.getClass() != Boat.class","boat_transfer_requires_private_singleplayer","isPublished()","BoatPassengerEnvelope.valid","hull.getXsize() > 1.5","boat_transfer_geometry_unknown"})assertTrue(s.contains(required),required);}
    @Test void commonDeadlineCancelCleanupAndInputGuardAreWired()throws Exception {String s=source("ClientActions.java");for(String required:new String[]{"case \"boat_mount\", \"boat_dismount\"", "a.transfer.inputRejection", "a.transfer.sneakInput", "cleanup(a.transfer::release)", "System.nanoTime() >= active.deadline", "finishAfterCleanup", "ACTIONS.existing(request)"})assertTrue(s.contains(required),required);String b=source("BoundedBoatTransfer.java");assertTrue(b.contains("input.shiftKeyDown = false"));assertTrue(b.contains("BoatInputRelease.clear(boat::setInput"));assertTrue(b.contains("landing_safety_confirmed"));}
    @Test void reentrantHookCannotDispatchOrFinishUnderANewerOwner()throws Exception {
        String b=source("BoundedBoatTransfer.java");
        int mark=b.indexOf("progress.dispatch(tick)");
        assertTrue(b.lastIndexOf("ClientActions.ownsTransfer(this)",mark)>b.indexOf("ClientHooks.onClickInput"));
        int interact=b.indexOf("mc.gameMode.interact(");
        assertTrue(b.indexOf("ClientActions.ownsTransfer(this)",interact)<b.indexOf("evidence.addProperty(\"interaction_result\"",interact));
        assertTrue(b.indexOf("ClientActions.ownsTransfer(this)",interact)<b.indexOf("player.swing(",interact));
        String a=source("ClientActions.java");
        String branch=a.substring(a.indexOf("case \"boat_mount\", \"boat_dismount\""),a.indexOf("case \"boat_drive\""));
        assertTrue(branch.indexOf("if (active != a) return")<branch.indexOf("finish(step.terminal()"));
        assertTrue(branch.contains("if (active == a) failException(failure)"));
        assertTrue(a.contains("active.transfer == transfer"));
    }

}
