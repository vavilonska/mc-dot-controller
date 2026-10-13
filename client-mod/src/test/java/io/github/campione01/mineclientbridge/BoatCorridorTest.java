package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class BoatCorridorTest {
 static BoatCorridor.Cell safe(int y){return new BoatCorridor.Cell(true,true,true,y<63,y>=63,false);}
 static BoatCorridor.Result check(BoatCorridor.Source source){return BoatCorridor.check(.5,.5,8,8,.6875,.6875,63,source);}
 @Test void clearLoadedStillDeepWaterAccepted(){assertTrue(check((x,y,z)->safe(y)).clear());}
 @Test void fullHullSweepIncludesMiddleNotOnlyEndpoints(){assertTrue(BoatCorridor.swept(.5,.5,8,8,.6875,.6875).contains(new BoatCorridor.Column(4,4)));assertFalse(check((x,y,z)->x==4&&z==4?null:safe(y)).clear());}
 @Test void squareSweepAvoidsBroadRectangleOffDiagonalCells(){assertFalse(BoatCorridor.swept(.5,.5,8,8,.6875,.6875).contains(new BoatCorridor.Column(0,8)));}
 @Test void unloadedAndUnknownFailClosed(){assertEquals("unknown",check((x,y,z)->null).reason());assertEquals("unloaded",check((x,y,z)->new BoatCorridor.Cell(false,false,false,false,false,false)).reason());}
 @Test void collisionContextFailureIsNotAir(){assertEquals("collision_unknown",check((x,y,z)->new BoatCorridor.Cell(true,false,true,true,true,false)).reason());assertEquals("cell_read_failed",check((x,y,z)->{throw new IllegalStateException();}).reason());}
 @Test void shallowWaterRockIceOrNonSourceWaterFails(){assertEquals("requires_deep_still_water",check((x,y,z)->y==61?new BoatCorridor.Cell(true,true,true,false,false,false):safe(y)).reason());assertEquals("collision",check((x,y,z)->new BoatCorridor.Cell(true,true,false,false,false,false)).reason());}
 @Test void bridgeAndOverheadFluidRejected(){assertEquals("requires_open_air",check((x,y,z)->y==65?new BoatCorridor.Cell(true,true,true,true,false,false):safe(y)).reason());}
 @Test void bubbleAndHazardRejected(){assertEquals("hazard",check((x,y,z)->new BoatCorridor.Cell(true,true,true,true,true,true)).reason());}
 @Test void sourceIsRereadEveryCheckForDynamicBlockChanges(){boolean[] blocked={false};BoatCorridor.Source source=(x,y,z)->blocked[0]?null:safe(y);assertTrue(check(source).clear());blocked[0]=true;assertFalse(check(source).clear());}
 @Test void waterSweepIsBoundedAndFinite(){assertThrows(IllegalArgumentException.class,()->BoatCorridor.swept(0,0,33,0,.7,.7));assertThrows(IllegalArgumentException.class,()->BoatCorridor.swept(0,0,Double.NaN,0,.7,.7));}
}
