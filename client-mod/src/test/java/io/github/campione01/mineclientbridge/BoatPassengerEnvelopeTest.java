package io.github.campione01.mineclientbridge;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BoatPassengerEnvelopeTest {
    static final double BOAT_Y=62.522468156083576;
    static final double FEET=BOAT_Y+.5625/3-.6;
    static BoatCollision.Box player(double x,double y,double z) {return body(x,y,z,(double).6f,(double)1.8f);}
    static BoatCollision.Box body(double x,double y,double z,double width,double height) {
        return new BoatCollision.Box(x-width/2,y,z-width/2,x+width/2,y+height,z+width/2);
    }
    static BoatPassengerEnvelope.Result check(BoatCollision.Box b) {return BoatPassengerEnvelope.inspect(b,b,8.5,56.5,63);}
    static BoatCorridor.Cell clear(int y) {return new BoatCorridor.Cell(true,true,true,y<63,y>=63,false);}

    @Test void officialMountFormulaExactlyReproducesRecordedFeet() {
        assertEquals(62.109968156083575,FEET,0);
        assertTrue(FEET<63-.8); // Regression: the old guard rejects this legitimate seat.
        var b=player(8.5,FEET,56.5);
        assertTrue(check(b).accepted());
        assertEquals(63.90996810839986,b.maxY(),1e-12);
    }
    @Test void normalPlayerFitsEveryBoatBuoyancyHeightWithoutChangingSurface() {
        for(double boatY:new double[]{62.2,62.3,BOAT_Y,62.8,62.95})
            assertTrue(check(player(8.5,boatY+.5625/3-.6,56.5)).accepted());
    }
    @Test void bambooNativeAttachmentUsesItsOwnHigherSeat() {
        assertTrue(check(player(8.5,BOAT_Y+(double)(.5625f*.8888889f)-.6,56.5)).accepted());
    }
    @Test void negativeWorldCoordinatesAndSurfaceTranslateIdentically() {
        var b=player(-21.5,-10+.5625/3-.6,-100.5);
        assertTrue(BoatPassengerEnvelope.inspect(b,b,-21.5,-100.5,-9).accepted());
    }
    @Test void lowerAndUpperBoundsFollowActuallyInspectedPrism() {
        assertTrue(check(body(8.5,61.1,56.5,.6,1.8)).accepted());
        assertEquals("unsupported_passenger_dimensions",check(body(8.5,61.1-1e-7,56.5,.6,1.8)).reason());
        assertTrue(check(body(8.5,64.1,56.5,.6,1.8)).accepted());
        assertEquals("unsupported_passenger_dimensions",check(body(8.5,64.1+1e-7,56.5,.6,1.8)).reason());
    }
    @Test void matchingButOversizedRidersStayRejected() {
        for(var b:new BoatCollision.Box[]{body(8.5,FEET,56.5,1.401,1.8),body(8.5,62,56.5,.6,2.901)})
            assertEquals("unsupported_passenger_dimensions",check(b).reason());
    }
    @Test void sidewaysOrVerticalSeatMismatchFailsClosed() {
        var expected=player(8.5,FEET,56.5);
        for(var actual:new BoatCollision.Box[]{player(8.501,FEET,56.5),player(8.5,FEET+.001,56.5),player(8.5,FEET,56.501),body(8.5,FEET,56.5,.5,1.8)})
            assertEquals("passenger_attachment_mismatch",BoatPassengerEnvelope.inspect(actual,expected,8.5,56.5,63).reason());
    }
    @Test void numericalEpsilonIsNotASeatTolerance() {
        var b=player(8.5,FEET,56.5);
        assertTrue(BoatPassengerEnvelope.inspect(player(8.5,FEET+1e-6,56.5),b,8.5,56.5,63).accepted());
        assertEquals("passenger_attachment_mismatch",BoatPassengerEnvelope.inspect(player(8.5,FEET+2e-5,56.5),b,8.5,56.5,63).reason());
    }
    @Test void incompleteAndNonFiniteGeometryFailsClosed() {
        var b=player(8.5,FEET,56.5);
        for(var bad:new BoatCollision.Box[]{null,new BoatCollision.Box(Double.NaN,FEET,56,9,64,57),new BoatCollision.Box(8,FEET,56,Double.POSITIVE_INFINITY,64,57),new BoatCollision.Box(9,FEET,56,8,64,57),new BoatCollision.Box(8,FEET,56,8,64,57),new BoatCollision.Box(8,FEET,56,9,FEET,57)}) {
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.inspect(bad,b,8.5,56.5,63).reason());
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.inspect(b,bad,8.5,56.5,63).reason());
        }
        assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.inspect(b,b,Double.NaN,56.5,63).reason());
    }
    @Test void farOffsetPassengerFailsRatherThanCreatingUnboundedSweep() {
        assertEquals("unsupported_passenger_dimensions",check(player(11,FEET,56.5)).reason());
    }
    @Test void offsetSecondSeatEnvelopeCoversEveryYawAndBodyCorner() {
        var b=player(8.5,FEET,55.9);double radius=check(b).radius();
        assertTrue(radius>.6875); // Second passenger protrudes beyond hull at some headings.
        for(int degrees=0;degrees<360;degrees++) {
            double yaw=Math.toRadians(degrees),cx=8.5+.6*Math.sin(yaw),cz=56.5-.6*Math.cos(yaw);
            for(double sx:new double[]{-1,1})for(double sz:new double[]{-1,1}) {
                assertTrue(Math.abs(cx+sx*(double).6f/2-8.5)<radius+1e-7);
                assertTrue(Math.abs(cz+sz*(double).6f/2-56.5)<radius+1e-7);
            }
        }
    }
    @Test void passengerSideColumnAndHeadroomAreStillRead() {
        double radius=check(player(8.5,FEET,55.9)).radius();
        var hullOnly=BoatCorridor.swept(8.5,56.5,0,8,.8875,.8875);
        var expanded=BoatCorridor.swept(8.5,56.5,0,8,radius+.2,radius+.2);
        assertTrue(expanded.containsAll(hullOnly));
        // Offsetting start to .1 places a second-seat-only column outside the old hull.
        assertTrue(BoatCorridor.swept(8.1,56.1,0,8,radius+.2,radius+.2).stream()
                .anyMatch(c->!BoatCorridor.swept(8.1,56.1,0,8,.8875,.8875).contains(c)));
        assertFalse(BoatCorridor.check(8.5,56.5,0,8,radius+.2,radius+.2,63,(x,y,z)->y==65?new BoatCorridor.Cell(true,true,false,false,false,false):clear(y)).clear());
    }
    @Test void correctedSeatCannotBypassFluidLoadAndCollisionHazards() {
        var b=player(8.5,FEET,56.5);assertTrue(check(b).accepted());
        for(var bad:new BoatCorridor.Cell[]{null,new BoatCorridor.Cell(false,false,false,false,false,false),new BoatCorridor.Cell(true,false,true,true,false,false),new BoatCorridor.Cell(true,true,false,true,false,false),new BoatCorridor.Cell(true,true,true,false,false,false),new BoatCorridor.Cell(true,true,true,true,false,true)})
            assertFalse(BoatCorridor.check(8.5,56.5,0,8,.8875,.8875,63,(x,y,z)->y==61?bad:clear(y)).clear());
    }

    @Test void unknownOrHorizontallyOffsetNativeAttachmentFailsClosed() {
        assertNull(BoatPassengerEnvelope.attachment(0,.6,0));
        assertNull(BoatPassengerEnvelope.attachment(0,-.2,0));
        for(double v:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY}) {
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.attachment(v,.6,0));
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.attachment(0,v,0));
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.attachment(0,.6,v));
        }
        assertEquals("unsupported_passenger_attachment",BoatPassengerEnvelope.attachment(.001,.6,0));
        assertEquals("unsupported_passenger_attachment",BoatPassengerEnvelope.attachment(0,.6,-.001));
    }
    @Test void illegalPassengerIdentityTopologyAndLivenessRemainRejected() {
        assertNull(BoatPassengerEnvelope.membership(1,1,true,true,false,0));
        assertNull(BoatPassengerEnvelope.membership(2,2,true,true,false,0));
        for(int count:new int[]{0,3})assertNotNull(BoatPassengerEnvelope.membership(count,count,true,true,false,0));
        assertNotNull(BoatPassengerEnvelope.membership(2,1,true,true,false,0));
        assertNotNull(BoatPassengerEnvelope.membership(1,1,false,true,false,0));
        assertNotNull(BoatPassengerEnvelope.membership(1,1,true,false,false,0));
        assertNotNull(BoatPassengerEnvelope.membership(1,1,true,true,true,0));
        assertNotNull(BoatPassengerEnvelope.membership(1,1,true,true,false,1));
    }
    @Test void everyCoordinateRejectsNanAndInfinities() {
        var expected=player(8.5,FEET,56.5);
        double[] points={expected.minX(),expected.minY(),expected.minZ(),expected.maxX(),expected.maxY(),expected.maxZ()};
        for(int i=0;i<6;i++)for(double bad:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY}) {
            double[] values=points.clone();values[i]=bad;
            var box=new BoatCollision.Box(values[0],values[1],values[2],values[3],values[4],values[5]);
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.inspect(box,expected,8.5,56.5,63).reason());
            assertEquals("passenger_geometry_unknown",BoatPassengerEnvelope.inspect(expected,box,8.5,56.5,63).reason());
        }
    }
    @Test void rotatingSecondSeatHazardInPassengerOnlyColumnCannotBeMissed() {
        double radius=check(player(8.5,FEET,55.9)).radius();
        var hull=BoatCorridor.swept(8.1,56.1,0,0,.8875,.8875);
        var expanded=BoatCorridor.swept(8.1,56.1,0,0,radius+.2,radius+.2);
        var extra=expanded.stream().filter(c->!hull.contains(c)).findFirst().orElseThrow();
        BoatCorridor.Source source=(x,y,z)->x==extra.x()&&z==extra.z()&&y==64
                ?new BoatCorridor.Cell(true,true,false,false,false,false):clear(y);
        assertTrue(BoatCorridor.check(8.1,56.1,0,0,.8875,.8875,63,source).clear());
        assertEquals("collision",BoatCorridor.check(8.1,56.1,0,0,radius+.2,radius+.2,63,source).reason());
    }
    @Test void widenedPassengerBodyProtectsEntitiesOutsideOldHull() {
        double radius=check(player(8.5,FEET,55.9)).radius();
        var oldHull=new BoatCollision.Box(8.5-.6875,60,56.5-.6875,8.5+.6875,66,56.5+.6875);
        var passengerBody=new BoatCollision.Box(8.5-radius,60,56.5-radius,8.5+radius,66,56.5+radius);
        var entity=new BoatCollision.Box(10.9,62,56.4,11.1,63,56.6);
        assertFalse(BoatCollision.protectedOverlap(oldHull,0,0,entity,0,0,0));
        assertTrue(BoatCollision.protectedOverlap(passengerBody,0,0,entity,0,0,0));
    }
}
