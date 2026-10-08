package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ExpeditionPrerequisitesContractTest {
    private String source(String file) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge",file));
    }
    @Test void guardIsBeforePathAndInputAndSamplesEvenWhenIdle() throws Exception {
        String s=source("ClientActions.java");
        assertTrue(s.indexOf("NavigationPositionGuard.tick(mc)")<s.indexOf("if (!context(mc)) return;"));
        assertTrue(s.contains("NavigationPositionGuard.requireBinding(mc, request)"));
        assertTrue(s.contains("active.navigationEpoch != NavigationPositionGuard.epoch()"));
        assertTrue(s.contains("finish(\"cancelled\", \"position_discontinuity_rebind_required\")"));
        assertTrue(s.contains("event.getEntity() != a.player || !context"));
        assertTrue(s.contains("input.forwardImpulse = a.forward"));
    }
    @Test void boundedComponentsDoNotExposeArbitraryPayloadOrRecurse() throws Exception {
        String s=source("BoundedContainerSnapshot.java");
        assertTrue(s.contains("remainingBoxes=4"));assertTrue(s.contains("Math.min(total,27)"));
        assertTrue(s.contains("Math.min(128,text.length())"));
        assertTrue(s.contains("identity_complete"));assertTrue(s.contains("slots_truncated"));
        assertTrue(s.contains("entry.getValue().isEmpty() ||"));
        assertTrue(s.contains("String text=name.getString(129)"));
        assertFalse(s.contains(".save("));assertFalse(s.contains("getComponents().toString"));
        assertFalse(s.contains("append(child"));
        String bridge=source("BridgeServer.java");
        assertTrue(bridge.contains("BoundedContainerSnapshot.append(stack, item)"));
        assertTrue(bridge.contains("world.add(\"navigation_guard\""));
    }
    @Test void noPrematureNativePearlOrSpecialCombatEnablement() throws Exception {
        assertFalse(source("ClientActionRequest.java").contains("use_item_once"));
        assertFalse(source("ClientActions.java").contains("useItem("));
        String combat=source("BoundedCombatRequest.java");
        for(String type:new String[]{"minecraft:blaze","minecraft:shulker","minecraft:ender_dragon"})
            assertFalse(combat.contains("\""+type+"\""));
    }
}
