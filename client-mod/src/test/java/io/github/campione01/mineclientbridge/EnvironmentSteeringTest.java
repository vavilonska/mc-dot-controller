package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
final class EnvironmentSteeringTest {
    @Test void onlyRecoveryAllowsEmptyPathAndGoalLifetime() {
        var r = ClientActionRequest.parse(com.google.gson.JsonParser.parseString(
                "{\"action_id\":\"recover\",\"action\":\"recover_environment\",\"waypoints\":[]}").getAsJsonObject());
        assertEquals(0, r.timeoutMs()); assertTrue(r.waypoints().isEmpty());
        assertThrows(ClientActionRequest.Rejected.class, () -> ClientActionRequest.parse(
                com.google.gson.JsonParser.parseString("{\"action_id\":\"ordinary\",\"action\":\"follow_path\",\"timeout_ms\":0,\"waypoints\":[]}").getAsJsonObject()));
    }
    @Test void waterHoldSurvivesAirborneAndThinkingGap() {
        for (int i=0;i<1200;i++) {
            var s=EnvironmentSteering.update(true,true,false,false,false,false,0);
            assertTrue(s.jump()); assertFalse(s.recovered());
        }
    }
    @Test void dryRequiresConsecutiveGroundedObservations() {
        int count=0;
        for(int i=0;i<5;i++) {var s=EnvironmentSteering.update(false,false,false,false,false,true,count);count=s.dryTicks();assertEquals(i==4,s.recovered());}
        assertEquals(0,EnvironmentSteering.update(true,false,false,false,false,true,count).dryTicks());
        assertFalse(EnvironmentSteering.update(false,false,false,false,false,false,4).recovered());
    }
    @Test void powderFireAndLavaAreNotMistakenForRecovery() {
        assertTrue(EnvironmentSteering.update(false,false,false,true,false,false,0).jump());
        assertTrue(EnvironmentSteering.update(false,false,true,false,false,false,0).jump());
        assertFalse(EnvironmentSteering.update(false,false,false,false,true,true,5).recovered());
    }
}
