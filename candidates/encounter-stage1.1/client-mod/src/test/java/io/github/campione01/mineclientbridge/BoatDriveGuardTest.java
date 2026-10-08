package io.github.campione01.mineclientbridge;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class BoatDriveGuardTest {
 static final BoatDriveGuard.Identity ID=new BoatDriveGuard.Identity("w","p","s","v",4,List.of("p","passenger"));
 static BoatDriveGuard.Sample sample(BoatDriveGuard.Identity id,boolean drive,boolean ordinary,boolean water,boolean bubble,boolean alive,boolean collision,double speed,double vy,double y){return new BoatDriveGuard.Sample(id,drive,ordinary,water,bubble,alive,collision,speed,vy,y,63);}
 static BoatDriveGuard.Sample good(BoatDriveGuard.Identity id){return sample(id,true,true,true,false,true,false,.2,0,62.8);}
 @Test void healthyDriverAccepted(){assertNull(BoatDriveGuard.reject(ID,good(ID)));}
 @Test void allSessionIdentitiesMatchExactly(){var ids=List.of(new BoatDriveGuard.Identity("other","p","s","v",4,ID.passengers()),new BoatDriveGuard.Identity("w","other","s","v",4,ID.passengers()),new BoatDriveGuard.Identity("w","p","other","v",4,ID.passengers()),new BoatDriveGuard.Identity("w","p","s","other",4,ID.passengers()),new BoatDriveGuard.Identity("w","p","s","v",5,ID.passengers()));for(var id:ids)assertNotNull(BoatDriveGuard.reject(ID,good(id)));}
 @Test void passengerIdentityOrderOrCountChangeStops(){for(var p:List.of(List.of("p"),List.of("passenger","p"),List.of("p","other")))assertEquals("passengers_changed",BoatDriveGuard.reject(ID,good(new BoatDriveGuard.Identity("w","p","s","v",4,p))));}
 @Test void nonDriverAndSpecialBoatRejected(){assertEquals("not_controlling_passenger",BoatDriveGuard.reject(ID,sample(ID,false,true,true,false,true,false,.1,0,62.8)));assertEquals("boat_type_unsupported",BoatDriveGuard.reject(ID,sample(ID,true,false,true,false,true,false,.1,0,62.8)));}
 @Test void airUnderwaterIceAndBubblesRejected(){assertEquals("requires_water_surface",BoatDriveGuard.reject(ID,sample(ID,true,true,false,false,true,false,.1,0,62.8)));assertEquals("bubble_column",BoatDriveGuard.reject(ID,sample(ID,true,true,true,true,true,false,.1,0,62.8)));}
 @Test void collisionDeathAndExcessVelocityRejected(){assertEquals("boat_collision",BoatDriveGuard.reject(ID,sample(ID,true,true,true,false,true,true,.1,0,62.8)));assertEquals("vehicle_unavailable",BoatDriveGuard.reject(ID,sample(ID,true,true,true,false,false,false,.1,0,62.8)));for(double speed:new double[]{.47,Double.NaN})assertEquals("boat_speed_unsafe",BoatDriveGuard.reject(ID,sample(ID,true,true,true,false,true,false,speed,0,62.8)));}
 @Test void fallingWaterfallsAndSurfaceChangeRejected(){assertEquals("vertical_motion_unsafe",BoatDriveGuard.reject(ID,sample(ID,true,true,true,false,true,false,.1,-.1,62.8)));assertEquals("water_surface_changed",BoatDriveGuard.reject(ID,sample(ID,true,true,true,false,true,false,.1,0,61.8)));}
}
