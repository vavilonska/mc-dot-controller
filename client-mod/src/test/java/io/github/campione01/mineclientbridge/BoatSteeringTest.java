package io.github.campione01.mineclientbridge;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class BoatSteeringTest {
 static BoatSteering.Pose p(double x,double z,double yaw,double vx,double vz,double rate){return new BoatSteering.Pose(x,z,yaw,vx,vz,rate);}
 static List<BoatSteering.Point> route(double x,double z){return List.of(new BoatSteering.Point(x,z));}
 @Test void straightTravelUsesForwardWithoutHeadLook() {var s=BoatSteering.step(p(0,0,0,0,.2,0),route(0,20),0);assertTrue(s.forward());assertFalse(s.left());assertFalse(s.right());}
 @Test void positiveYawErrorUsesRightAndNegativeUsesLeft() {assertTrue(BoatSteering.step(p(0,0,0,0,0,0),route(-10,0),0).right());assertTrue(BoatSteering.step(p(0,0,0,0,0,0),route(10,0),0).left());}
 @Test void steeringCountersAngularInertiaBeforeOvershoot() {var s=BoatSteering.step(p(0,0,0,0,.1,3),route(0,20),0);assertTrue(s.left());assertFalse(s.right());}
 @Test void waypointTransitionDoesNotInsertNeutralFrame() {var points=List.of(new BoatSteering.Point(0,8),new BoatSteering.Point(0,16));var s=BoatSteering.step(p(0,7.5,0,0,.2,0),points,0);assertEquals(1,s.waypoint());assertTrue(s.forward());assertFalse(s.atEndpoint());}
 @Test void brakeBeforeEndpointAndBeforeHardCorner() {var end=BoatSteering.step(p(0,0,0,0,.3,0),route(0,2),0);assertTrue(end.backward());assertFalse(end.forward());var corner=BoatSteering.step(p(0,5,0,0,.2,0),List.of(new BoatSteering.Point(0,8),new BoatSteering.Point(8,8)),0);assertTrue(corner.backward());}
 @Test void endpointCounterthrustDoesNotConfuseInputReleaseAndSettlement() {var moving=BoatSteering.step(p(0,7.8,0,0,.2,0),route(0,8),0);assertTrue(moving.atEndpoint());assertTrue(moving.backward());assertFalse(moving.settled());var still=BoatSteering.step(p(0,7.8,0,0,0,0),route(0,8),0);assertTrue(still.settled());assertFalse(still.backward());}
 @Test void reverseDriftBrakesWithForwardButLateralDriftCoasts() {assertTrue(BoatSteering.step(p(0,8,0,0,-.1,0),route(0,8),0).forward());var side=BoatSteering.step(p(0,8,0,.1,0,0),route(0,8),0);assertFalse(side.forward());assertFalse(side.backward());assertFalse(side.settled());}
 @Test void rotationMustAlsoSettle() {var s=BoatSteering.step(p(0,8,0,0,0,2),route(0,8),0);assertFalse(s.settled());assertTrue(s.left());}
 @Test void brakingHorizonGrowsWithInertiaAndIsFinite() {assertEquals(2,BoatSteering.safetyDistance(0));assertEquals(6,BoatSteering.safetyDistance(.4));}
 @Test void invalidTelemetryRejected() {assertThrows(IllegalArgumentException.class,()->BoatSteering.step(p(0,0,Double.NaN,0,0,0),route(0,8),0));}
 @Test void deterministicStraightNativeFormulaModelReachesAndSettles() {
  // Regression model from cached 1.21.1 bytecode: .9 drag, +.04/- .005 thrust.
  // This is NOT an actual Minecraft integration/simulation acceptance.
  double z=0,v=0;int index=0,stable=0,lock=0;var points=List.of(new BoatSteering.Point(0,8),new BoatSteering.Point(0,16),new BoatSteering.Point(0,24));
  for(int tick=0;tick<1600;tick++) {var decision=BoatSteering.decide(p(0,z,0,0,v,0),points,index,lock);var s=decision.step();lock=decision.turnLock();index=s.waypoint();v=.9*v+(s.forward()?.04:0)-(s.backward()?.005:0);z+=v;if(s.settled())stable++;else stable=0;if(stable>=4)break;}
  assertEquals(2,index);assertTrue(stable>=4,"z="+z+", v="+v);assertTrue(Math.abs(z-24)<=BoatSteering.ARRIVAL_RADIUS);
 }
 @Test void deterministicTurningFormulaModelsSettleWithoutAngularLimitCycle() {
  for(var points:List.of(List.of(new BoatSteering.Point(0,8),new BoatSteering.Point(8,8),new BoatSteering.Point(8,16)),route(0,-16),route(-16,0),route(16,16))) {
   double x=0,z=0,yaw=0,vx=0,vz=0,rate=0;int index=0,stable=0,lock=0;
   for(int tick=0;tick<1600;tick++) {
    var decision=BoatSteering.decide(p(x,z,yaw,vx,vz,rate),points,index,lock);var s=decision.step();lock=decision.turnLock();index=s.waypoint();
    if(s.settled())stable++;else stable=0;if(stable>=4)break;
    rate=.9*rate+(s.left()?-1:0)+(s.right()?1:0);yaw+=rate;
    double f=(s.forward()?.04:0)-(s.backward()?.005:0)+((s.left()!=s.right()&&!s.forward()&&!s.backward())?.005:0);
    vx=.9*vx-Math.sin(Math.toRadians(yaw))*f;vz=.9*vz+Math.cos(Math.toRadians(yaw))*f;x+=vx;z+=vz;
   }
   assertEquals(points.size()-1,index);assertTrue(stable>=4,"x="+x+", z="+z+", yawRate="+rate);
  }
 }

 @Test void actualOneTickInputPipelineHandlesNearReverseHeadingAndInertia() {
  for(double[] initial:new double[][]{{175,1.2},{173,1.6},{177,.7},{-175,-1.2},{179.5,.6},{180.5,-.6},{178,1.9},{180,0},{0,0}}) {
   var points=route(0,8);double x=0,z=0,yaw=initial[0],vx=0,vz=0,rate=initial[1];int index=0,stable=0,lock=0;
   var queued=new BoatSteering.Step(0,false,false,false,false,false,false,"initial-neutral",0);
   for(int tick=0;tick<1600;tick++) {
    assertTrue(BoatCollision.distanceToSegment(x,z,new BoatSteering.Point(0,0),points.getLast())<=2.5,"route deviation at "+yaw+", "+x+", "+z);
    var output=BoatSteering.decide(p(x,z,yaw,vx,vz,rate),points,index,lock);
    var decision=output.step();lock=output.turnLock();index=decision.waypoint();
    if(decision.settled())stable++;else stable=0;if(stable>=4)break;
    // Boat.tick consumes the PREVIOUS rideTick input before LocalPlayer.rideTick
    // copies this tick's MovementInputUpdateEvent decision into Boat.setInput.
    var s=queued;queued=decision;
    rate=.9*rate+(s.left()?-1:0)+(s.right()?1:0);yaw+=rate;
    double f=(s.forward()?.04:0)-(s.backward()?.005:0)+((s.left()!=s.right()&&!s.forward()&&!s.backward())?.005:0);
    vx=.9*vx-Math.sin(Math.toRadians(yaw))*f;vz=.9*vz+Math.cos(Math.toRadians(yaw))*f;x+=vx;z+=vz;
   }
   assertTrue(stable>=4,"heading="+initial[0]+", rate="+initial[1]+", final="+x+","+z);
  }
 }

 @Test void reverseTurnLockHasSeparateEntryAndExitBoundaries() {
  assertEquals(1,BoatSteering.turn(-160,.6,0).lock());
  assertEquals(1,BoatSteering.turn(-149,-.6,1).lock());
  assertEquals(1,BoatSteering.turn(100,-.6,1).lock());
  assertEquals(0,BoatSteering.turn(89,-.6,1).lock());
 }

 @Test void maximumLengthStraightRoutesSettleWithOneTickInputPipeline() {
  // Both fixtures use the full 256-block route budget, including the first leg.
  // The second also uses all 64 admitted waypoints, without append or renewal.
  for(int count:new int[]{16,64}) {
   var points=new java.util.ArrayList<BoatSteering.Point>();
   for(int i=1;i<=count;i++)points.add(new BoatSteering.Point(0,i*(256.0/count)));
   assertDelayedModelSettlesWithinGuards(points);
  }
 }

 @Test void multiWaypointTurnsRespectDeviationGuardWithOneTickInputPipeline() {
  for(int direction:new int[]{-1,1}) {
   assertDelayedModelSettlesWithinGuards(List.of(new BoatSteering.Point(0,8),
           new BoatSteering.Point(direction*8,8),new BoatSteering.Point(direction*8,16)));
   // Include shallow corners, right angles, and a reversal; each second leg is 8 blocks.
   for(int angle=15;angle<=180;angle+=15) {
    double radians=Math.toRadians(direction*angle);
    assertDelayedModelSettlesWithinGuards(List.of(new BoatSteering.Point(0,8),
            new BoatSteering.Point(-8*Math.sin(radians),8+8*Math.cos(radians))));
   }
  }
 }

 @Test void waypointTransitionClearsPreviousReverseTurnLock() {
  for(int direction:new int[]{-1,1}) {
   var points=List.of(new BoatSteering.Point(0,8),new BoatSteering.Point(direction*8,0));
   // This 90–150 degree turn does not clear or acquire a lock by angle alone.
   // A stale lock from the preceding segment points away from the new corner.
   var decision=BoatSteering.decide(p(0,7.5,0,0,.05,0),points,0,direction);
   assertEquals(1,decision.step().waypoint());
   assertEquals(0,decision.turnLock());
   assertEquals(direction>0,decision.step().left());
   assertEquals(direction<0,decision.step().right());
  }
 }

 private static void assertDelayedModelSettlesWithinGuards(List<BoatSteering.Point> points) {
  // Deterministic still-water formula regression ONLY, not Minecraft acceptance.
  // One iteration models one 20 Hz client tick; 2400 ticks is the maximum 120 s
  // lease at that rate, not a wall-clock deadline guarantee under a delayed client.
  // Native Boat.tick consumes the preceding rideTick input. Pose is observed and
  // checked against the CURRENT segment before this tick advances its waypoint.
  double x=0,z=0,yaw=0,vx=0,vz=0,rate=0;
  int index=0,stable=0,lock=0;
  var start=new BoatSteering.Point(0,0);
  var queued=new BoatSteering.Step(0,false,false,false,false,false,false,"initial-neutral",0);
  for(int tick=0;tick<2400;tick++) {
   var previous=index==0?start:points.get(index-1);
   assertTrue(BoatCollision.distanceToSegment(x,z,previous,points.get(index))<=2.5,
           "route deviation at tick="+tick+", waypoint="+index+", position="+x+","+z);
   assertTrue(Math.hypot(vx,vz)<=BoatSteering.MAX_SPEED,"speed guard at tick="+tick);
   var decision=BoatSteering.decide(p(x,z,yaw,vx,vz,rate),points,index,lock);
   var output=decision.step();
   assertTrue(output.waypoint()>=index,"waypoint progress must be monotonic");
   index=output.waypoint();lock=decision.turnLock();
   if(output.settled())stable++;else stable=0;
   if(stable>=4) {
    assertEquals(points.size()-1,index);
    assertTrue(new BoatSteering.Point(x,z).distance(points.getLast())<=BoatSteering.ARRIVAL_RADIUS);
    return;
   }
   var input=queued;queued=output;
   rate=.9*rate+(input.left()?-1:0)+(input.right()?1:0);yaw+=rate;
   double thrust=(input.forward()?.04:0)-(input.backward()?.005:0)
           +((input.left()!=input.right()&&!input.forward()&&!input.backward())?.005:0);
   vx=.9*vx-Math.sin(Math.toRadians(yaw))*thrust;
   vz=.9*vz+Math.cos(Math.toRadians(yaw))*thrust;
   x+=vx;z+=vz;
  }
  fail("model did not settle within maximum modeled lease: waypoint="+index+", position="+x+","+z);
 }

}
