package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class BoatCollisionTest {
 static final BoatCollision.Box HULL=new BoatCollision.Box(-.7,62.8,-.7,.7,65,.7);
 static BoatCollision.Box entity(double x,double z) {return new BoatCollision.Box(x-.3,63,z-.3,x+.3,64.8,z+.3);}
 @Test void futureHullProtectsBystanderBetweenEndpoints(){assertTrue(BoatCollision.protectedOverlap(HULL,0,6,entity(0,3),0,0,0));}
 @Test void movingBystanderCrossingRouteIsProtected(){assertTrue(BoatCollision.protectedOverlap(HULL,0,6,entity(5,3),-.25,0,0));}
 @Test void clearDistantEntityDoesNotBlock(){assertFalse(BoatCollision.protectedOverlap(HULL,0,6,entity(8,0),0,0,0));}
 @Test void uncertainFastOrNonfiniteMovementFailsClosed(){assertTrue(BoatCollision.protectedOverlap(HULL,0,6,entity(8,0),2,0,0));assertTrue(BoatCollision.protectedOverlap(HULL,0,6,entity(8,0),0,Double.NaN,0));}
 @Test void malformedEntityBoundsFailClosed(){assertTrue(BoatCollision.protectedOverlap(HULL,0,6,new BoatCollision.Box(Double.NaN,0,0,1,1,1),0,0,0));}
 @Test void requestRouteDeviationCannotBeHiddenByEndpointDistance(){var a=new BoatSteering.Point(0,0);var b=new BoatSteering.Point(0,16);assertEquals(3,BoatCollision.distanceToSegment(3,8,a,b));assertEquals(4,BoatCollision.distanceToSegment(0,20,a,b));assertEquals(0,BoatCollision.distanceToSegment(0,8,a,b));}
}
