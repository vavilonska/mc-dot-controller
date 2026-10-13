package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Source wiring regressions only, separate from executed pure policy tests. */
class CapabilityTargetLifecycleContractTest {
    private String source(String file)throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge",file));
    }
    @Test void reentrantTargetFailureCannotFinishAReplacementOwner()throws Exception {
        String s=source("ClientActions.java");
        int start=s.indexOf("case \"attack_entity\", \"shoot_entity\" -> {",s.indexOf("private static void preTick()"));
        String branch=s.substring(start,s.indexOf("case \"combat_entity\"",start));
        assertTrue(branch.contains("try { step=a.capabilityTarget.tick(mc); }"));
        assertTrue(branch.contains("catch (RuntimeException failure) { if (active == a) failException(failure); return; }"));
        assertTrue(branch.indexOf("if(active!=a)return;")<branch.indexOf("a.entry.result.add("));
    }
    @Test void itemEffectsAreFencedAndResumedBowCannotClearNewOwnerInput()throws Exception {
        String s=source("CapabilityTargetAction.java");
        assertTrue(s.contains("itemUseTransition.run(()->mc.gameMode.useItem(player,InteractionHand.MAIN_HAND))"));
        assertTrue(s.contains("itemUseTransition.run(()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND))"));
        int dispatch=s.indexOf("ClientActions.markCapabilityDispatched(this)");
        int release=s.indexOf("itemUseTransition.run(()->mc.gameMode.releaseUsingItem(player))",dispatch);
        int owner=s.indexOf("if(!ClientActions.ownsCapabilityTarget(this))",release);
        int key=s.indexOf("mc.options.keyUse.setDown(false)",release);
        assertTrue(release>dispatch && owner>release && key>owner);
        assertTrue(s.contains("if(!itemUseTransition.cleanupMayConfirm())throw"));
    }
    @Test void outgoingExemptionIsOnlyNewExactSelfOwnedVanillaArrowsAfterRelease()throws Exception {
        String s=source("CapabilityTargetAction.java");
        assertTrue(s.contains("if(!covered && !outgoingOwnArrow(e,type))return \"nearby_projectile\""));
        int start=s.indexOf("private boolean outgoingOwnArrow(");
        String method=s.substring(start,s.indexOf("private boolean sameShield()",start));
        for(String required:new String[]{"!shieldWindow || !dispatched || !released", "AbstractArrow arrow",
                "type.equals(\"minecraft:arrow\")", "type.equals(\"minecraft:spectral_arrow\")",
                "arrow.getOwner()!=player", "projectilesBeforeShot.contains(entity.getUUID())",
                "BlazeShieldPolicy.outgoingArrow"})assertTrue(method.contains(required),required);
        assertTrue(s.indexOf("projectilesBeforeShot.add(existing.getUUID())")<s.indexOf("ClientActions.markCapabilityDispatched(this)"));
    }

    @Test void liveEncounterAndShellChecksSurroundAdmissionAndEveryOwnedCallback() throws Exception {
        String guard=source("CapabilityGuard.java"),target=source("CapabilityTargetAction.java"),server=source("BridgeServer.java");
        assertTrue(guard.contains("CapabilityEncounterRoute.check(mc,request)"));
        assertTrue(source("BoundedCombat.java").contains("healthGuard=new CombatThreats.HealthGuard(request.minHealth())"));
        assertTrue(source("BoundedCombat.java").contains("healthGuard.sample(tick, System.nanoTime(), mc.player.getHealth())"));
        assertTrue(guard.contains("dispatched?null:CapabilityTargetAction.shulkerAdmission(mc,request)"));
        assertTrue(target.contains("shulker.getRawPeekAmount(),shulker.getClientPeekAmount(1.0F)"));
        assertFalse(target.contains("enderman.getTarget()!=player"));
        assertTrue(target.contains("NativeLivingObservation.knownCalmTargetless(mc,e,livingFrame)"));
        assertTrue(source("CapabilityEncounterRoute.java").contains("NativeLivingObservation.knownCalmTargetless(mc,entity,livingFrame)"));
        assertTrue(target.contains("!dispatched && t instanceof net.minecraft.world.entity.monster.Shulker shulker"));
        assertTrue(target.contains("&&!shulkerShellOpen(shulker))return \"shulker_shell_not_open\""));
        assertTrue(server.contains("obj.add(\"combat_capabilities\",CapabilityCombatSafety.capabilities())"));
        assertTrue(server.contains("entityJson.addProperty(\"shell_open\",CapabilityTargetAction.shulkerShellOpen(shulker))"));
        int release=target.indexOf("ClientActions.markCapabilityDispatched(this)");
        assertTrue(target.lastIndexOf("problem=guard(mc);if(problem!=null)return done(\"failed\",problem);",release)>target.indexOf("if(player.getTicksUsingItem()<drawTicks)"));
    }
}
