package io.github.campione01.mineclientbridge;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class PathArrivalTest {
    final ClientActionRequest.Point goal=new ClientActionRequest.Point(4.5,65,2.5,true);
    @Test void airborneNearEndpointIsNotSettled() {
        assertFalse(PathSteering.settledAt(4.4,65.1,2.5,.02,0,false,goal));
        assertFalse(PathSteering.settledAt(4.33,65.42,2.5,.12,0,false,goal));
    }
    @Test void landedMomentumOrOvershootIsNotArrival() {
        assertFalse(PathSteering.settledAt(4.5,65,2.5,.1,0,true,goal));
        assertFalse(PathSteering.settledAt(5.027,65,2.5,0,0,true,goal));
        assertTrue(PathSteering.settledAt(4.55,65,2.5,.01,0,true,goal));
    }
    @Test void finalVerticalToleranceDoesNotAcceptMidJumpHeight() {
        assertTrue(PathSteering.toward(4.4,65.42,2.5,0,false,false,goal).reached());
        assertFalse(PathSteering.toward(4.4,65.42,2.5,0,false,false,goal,true).reached());
    }
    @Test void invalidVelocityDoesNotSatisfySettle() {
        assertFalse(PathSteering.settledAt(4.5,65,2.5,Double.NaN,0,true,goal));
    }
    @Test void sprintIsBooleanAndOnlyForPathRequests() {
        var b=JsonParser.parseString("{\"action_id\":\"a\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"y\":64,\"z\":1}],\"sprint\":true}").getAsJsonObject();
        assertEquals("follow_path",ClientActionRequest.parse(b).action());
        b.addProperty("sprint","true");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
    }
    @Test void runtimeConsumesExplicitJumpAndReleasesSprintWithoutMotionWrites() throws Exception {
        var p=Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/ClientActions.java");
        String s=Files.readString(p);
        assertTrue(s.contains("goal.jump() && !a.waypointJumped"));
        assertTrue(s.contains("if (a.jump) a.waypointJumped=true"));
        assertTrue(s.contains("a.settledTicks < 2"));
        assertTrue(s.contains("SprintKeyState.set(mc.options.keySprint::isDown,mc.options.keySprint::setDown,true)"));
        assertTrue(s.contains("SprintKeyState.set(mc.options.keySprint::isDown,mc.options.keySprint::setDown,false)"));
        assertFalse(s.contains("setSprinting(true)"));
        assertFalse(s.contains("setDeltaMovement("));
        assertFalse(s.contains("setPos("));
    }
}
