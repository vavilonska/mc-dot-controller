package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PositionDiscontinuityGuardTest {
    Object world=new Object(),player=new Object();
    PositionDiscontinuityGuard.Sample at(double x,double y,double z) {
        return new PositionDiscontinuityGuard.Sample(x,y,z,0,0,0,true,true,true,false);
    }
    void sample(PositionDiscontinuityGuard guard,double x,long tick) { guard.sample(world,player,at(x,64,0),tick); }
    JsonObject binding(long epoch,double x) {
        return JsonParser.parseString("{\"expected_navigation_epoch\":"+epoch+",\"expected_origin\":{\"x\":"+x+",\"y\":64,\"z\":0}}").getAsJsonObject();
    }
    @Test void walksJumpsAndOrdinaryKnockbackDoNotInvalidate() {
        var g=new PositionDiscontinuityGuard();
        for(int i=0;i<100;i++) sample(g,i*.4,i);
        g.sample(world,player,new PositionDiscontinuityGuard.Sample(43,65,2,1,.4,.2,false,true,false,false),100);
        sample(g,44,101);
        assertEquals(0,g.epoch());
        g.requireBinding(new JsonObject());
    }
    @Test void velocityConsistentLongFallIsNotCalledTeleport() {
        var g=new PositionDiscontinuityGuard();
        g.sample(world,player,new PositionDiscontinuityGuard.Sample(0,100,0,0,-20,0,false,true,false,false),0);
        g.sample(world,player,new PositionDiscontinuityGuard.Sample(0,80,0,0,-20,0,false,true,false,false),1);
        assertEquals(0,g.epoch());
    }
    @Test void sameDimensionLargeMoveInvalidatesAndRequiresFreshOrigin() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);sample(g,1000,1);
        assertEquals(1,g.epoch()); assertFalse(g.ready());
        assertEquals("navigation_rebind_required",assertThrows(ClientActionRequest.Rejected.class,
                ()->g.requireBinding(new JsonObject())).getMessage());
        sample(g,1000,2);sample(g,1000,3);
        assertTrue(g.ready());g.requireBinding(binding(1,1000));
        assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(binding(0,1000)));
        assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(binding(1,0)));
        // Binding does not make later unbound stale paths valid.
        assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(new JsonObject()));
    }
    @Test void repeatedSnapshotsCannotInventSettledTicks() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);sample(g,1000,1);
        for(int i=0;i<50;i++) sample(g,1000,1);
        assertFalse(g.ready());
        assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(binding(1,1000)));
    }
    @Test void unsupportedUnloadedAirborneOrRidingCannotRebind() {
        for(int kind=0;kind<4;kind++) {
            var g=new PositionDiscontinuityGuard();sample(g,0,0);sample(g,1000,1);
            for(int t=2;t<10;t++) g.sample(world,player,new PositionDiscontinuityGuard.Sample(1000,64,0,0,0,0,
                    kind!=0,kind!=1,kind!=2,kind==3),t);
            assertFalse(g.ready());
        }
    }
    @Test void movingExitAndSecondTeleportRestartSettleBudget() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);sample(g,1000,1);sample(g,1000,2);
        g.sample(world,player,new PositionDiscontinuityGuard.Sample(1000,64,0,0,.8,0,true,true,true,false),3);
        assertFalse(g.ready());sample(g,2000,4);assertEquals(2,g.epoch());assertFalse(g.ready());
    }
    @Test void identityAndInvalidPositionFailClosed() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);
        g.sample(new Object(),player,at(0,64,0),1);assertEquals(1,g.epoch());
        g.sample(null,null,null,2);assertEquals(2,g.epoch());assertFalse(g.ready());
        g.sample(world,player,at(Double.NaN,64,0),3);assertFalse(g.ready());
    }
    @Test void aSecondInvalidObservationEpisodeInvalidatesNewlyBoundAction() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);
        g.sample(world,player,at(Double.NaN,64,0),1);assertEquals(1,g.epoch());
        g.sample(world,player,at(Double.NaN,64,0),2);assertEquals(1,g.epoch());
        sample(g,0,3);sample(g,0,4);sample(g,0,5);g.requireBinding(binding(1,0));
        g.sample(world,player,at(Double.NaN,64,0),6);assertEquals(2,g.epoch());assertFalse(g.ready());
        assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(binding(1,0)));
    }
    @Test void strictBindingRejectsNumericStringsMissingCoordinatesAndFractions() {
        var g=new PositionDiscontinuityGuard();sample(g,0,0);sample(g,1000,1);sample(g,1000,2);sample(g,1000,3);
        for(String text:new String[]{"{\"expected_navigation_epoch\":\"1\"}","{\"expected_navigation_epoch\":1.5}",
                "{\"expected_navigation_epoch\":1}","{\"expected_navigation_epoch\":1,\"expected_origin\":{}}"})
            assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(JsonParser.parseString(text).getAsJsonObject()));
    }
}
