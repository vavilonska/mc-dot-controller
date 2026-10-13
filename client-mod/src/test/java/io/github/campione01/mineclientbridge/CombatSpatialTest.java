package io.github.campione01.mineclientbridge;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CombatSpatialTest {
    static CombatSpatial.Box box(int id,double x,double z) { return new CombatSpatial.Box(id,x,64,z,x+.6,65.8,z+.6); }
    @Test void dynamicEntityInMidSegmentBlocksEvenClearEndpoints() {
        assertFalse(CombatSpatial.check(0,64,0,2,0,List.of(box(7,.7,-.3))).clear());
    }
    @Test void diagonalBroadPhaseCornerNotActuallyCrossedRemainsClear() {
        assertTrue(CombatSpatial.check(.5,64,.5,.65,.65,List.of(box(1,.04,1.55))).clear());
    }
    @Test void actualDiagonalIntersectionFails() {
        var r=CombatSpatial.check(.5,64,.5,.65,.65,List.of(box(4,1,1)));
        assertFalse(r.clear());assertEquals(4,r.entityId());
    }
    @Test void stationaryOverlappingEntityBlocks() {
        assertFalse(CombatSpatial.check(.5,64,.5,0,0,List.of(box(3,.5,.5))).clear());
    }
    @Test void entityAbovePlayerNotBlockingSameFloor() {
        assertTrue(CombatSpatial.check(.5,64,.5,.6,0,List.of(new CombatSpatial.Box(9,0,67,0,2,69,2))).clear());
    }
    @Test void unknownOversizedAndNonfiniteInputsFailClosed() {
        assertFalse(CombatSpatial.check(0,64,0,.5,0,null).clear());
        assertFalse(CombatSpatial.check(0,64,0,Double.NaN,0,List.of()).clear());
        assertFalse(CombatSpatial.check(0,64,0,2.01,0,List.of()).clear());
        assertFalse(CombatSpatial.check(0,64,0,.5,0,java.util.Collections.nCopies(129,box(1,4,4))).clear());
        assertFalse(CombatSpatial.check(0,64,0,.5,0,List.of(new CombatSpatial.Box(1,Double.NaN,0,0,1,1,1))).clear());
    }
    @Test void activityBoundIncludesHeightAfterRecoveryAndCannotCrossSphere() {
        assertTrue(CombatSpatial.withinCombatArea(12,64,0,0,64,0));
        assertFalse(CombatSpatial.withinCombatArea(11.99,65,0,0,64,0));
        assertTrue(CombatSpatial.withinCombatArea(11.9,65,0,0,64,0));
        assertFalse(CombatSpatial.withinCombatArea(Double.NaN,64,0,0,64,0));
    }
    @Test void dynamicObstacleRecheckedFromActualNewPose() {
        assertTrue(CombatSpatial.check(0,64,0,.65,0,List.of(box(2,3,3))).clear());
        assertFalse(CombatSpatial.check(.2,64,.1,.65,0,List.of(box(2,.7,0))).clear());
    }
}
