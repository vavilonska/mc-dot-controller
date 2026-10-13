package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GatewayTrajectoryTest {
    @Test void closeHorizontalPlanFitsWholeLaunchEnvelope() {
        var p=GatewayTrajectory.plan(3,0,0,0,0);assertNotNull(p);assertEquals(2,p.insideTick());
        var end=p.points().get(p.insideTick());
        assertTrue(Math.abs(end.x()-3)+end.uncertainty()+GatewayTrajectory.RADIUS<.5);
        assertTrue(Math.abs(end.y())+end.uncertainty()+GatewayTrajectory.RADIUS<.5);
        assertEquals(p.insideTick()+2,p.points().size()); // Includes collision-before-portal next sweep.
    }
    @Test void allExtremeSpreadCornersAreInsideProvenEnvelope() {
        var p=GatewayTrajectory.plan(3,.1,0,.004,0);assertNotNull(p);
        for(int mask=0;mask<8;mask++) {
            double vx=p.vx()+.004+((mask&1)==0?-1:1)*.0172275*1.5;
            double vy=p.vy()+((mask&2)==0?-1:1)*.0172275*1.5;
            double vz=p.vz()+((mask&4)==0?-1:1)*.0172275*1.5;
            double x=0,y=0,z=0;
            for(int i=1;i<=p.insideTick();i++) {
                x+=vx;y+=vy;z+=vz;vx*=GatewayTrajectory.DRAG;vy=vy*GatewayTrajectory.DRAG-.03;vz*=GatewayTrajectory.DRAG;
                var nominal=p.points().get(i);
                assertTrue(Math.abs(x-nominal.x())<nominal.uncertainty());
                assertTrue(Math.abs(y-nominal.y())<nominal.uncertainty());
                assertTrue(Math.abs(z-nominal.z())<nominal.uncertainty());
            }
            assertTrue(Math.abs(x-3)+.125<.5);assertTrue(Math.abs(y-.1)+.125<.5);assertTrue(Math.abs(z)+.125<.5);
        }
    }
    @Test void distantUnknownAndFastInheritedMotionNeverAdmit() {
        assertNull(GatewayTrajectory.plan(16,0,0,0,0));assertNull(GatewayTrajectory.plan(Double.NaN,0,0,0,0));
        assertNull(GatewayTrajectory.plan(3,0,0,.02,0));assertNull(GatewayTrajectory.plan(0,0,0,0,0));
    }
    @Test void physicsUsesDiscreteDragGravityAndBoundedTriangleSpread() {
        var p=GatewayTrajectory.plan(3,0,0,0,0);var first=p.points().get(1);var second=p.points().get(2);
        assertEquals(first.x()+p.vx()*GatewayTrajectory.DRAG,second.x(),1e-12);
        assertEquals(first.y()+p.vy()*GatewayTrajectory.DRAG-.03,second.y(),1e-12);
        assertTrue(second.uncertainty()>first.uncertainty());
    }
}
