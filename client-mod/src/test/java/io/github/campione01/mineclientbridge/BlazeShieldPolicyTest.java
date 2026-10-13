package io.github.campione01.mineclientbridge;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Pure policy execution; does not start Minecraft or assert a live volley result. */
class BlazeShieldPolicyTest {
    @Test void coverRequiresObservedChargeCooldownAndNoRemainingProjectile() {
        assertFalse(BlazeShieldPolicy.initialReady(false,20,false,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,19,false,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,20,true,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,20,false,true));
        assertTrue(BlazeShieldPolicy.initialReady(true,20,false,false));
        assertTrue(BlazeShieldPolicy.initialReady(true,240,false,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,241,false,false));
        assertFalse(BlazeShieldPolicy.ready(19,false,false));
        assertTrue(BlazeShieldPolicy.ready(20,false,false));
        assertFalse(BlazeShieldPolicy.ready(20,true,false));
        assertFalse(BlazeShieldPolicy.ready(20,false,true));
        assertTrue(BlazeShieldPolicy.ready(120,false,false));
        assertFalse(BlazeShieldPolicy.ready(121,false,false));
    }
    @Test void exact64DurabilityReserveAndInvalidDamageAreFailClosed() {
        assertTrue(BlazeShieldPolicy.reserve(336,272));
        assertFalse(BlazeShieldPolicy.reserve(336,273));
        assertFalse(BlazeShieldPolicy.reserve(336,-1));
        assertFalse(BlazeShieldPolicy.reserve(336,337));
        assertFalse(BlazeShieldPolicy.reserve(0,0));
    }
    @Test void releasedArrowMayStartAtEyesOrMoveOutwardAlongShot() {
        assertTrue(BlazeShieldPolicy.outgoingArrow(0,0,0,3,0,1));
        assertTrue(BlazeShieldPolicy.outgoingArrow(0,3,0,2.97,0,1));
        assertTrue(BlazeShieldPolicy.outgoingArrow(-3,0,-2.97,0,-1,0));
    }
    @Test void returningStoppedCrossingBehindAndNonfiniteArrowsRemainThreats() {
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,3,0,-3,0,1));
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,3,0,0,0,1));
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,3,3,0,0,1));
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,-1,0,3,0,1));
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,3,0,3,0,0));
        assertFalse(BlazeShieldPolicy.outgoingArrow(Double.NaN,3,0,3,0,1));
        assertFalse(BlazeShieldPolicy.outgoingArrow(0,3,0,Double.POSITIVE_INFINITY,0,1));
    }
}
