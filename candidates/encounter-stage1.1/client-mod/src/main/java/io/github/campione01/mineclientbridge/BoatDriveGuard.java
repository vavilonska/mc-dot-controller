package io.github.campione01.mineclientbridge;

import java.util.List;

/** Deterministic identity and hard safety guard, independent of rendering/model cadence. */
final class BoatDriveGuard {
    record Identity(String world,String player,String session,String vehicle,int vehicleId,List<String> passengers) { }
    record Sample(Identity identity,boolean driving,boolean ordinaryBoat,boolean water,boolean bubble,
                  boolean alive,boolean collision,double speed,double verticalSpeed,double y,int surfaceY) { }
    static String reject(Identity expected,Sample sample) {
        if (sample==null || sample.identity==null) return "vehicle_missing";
        var id=sample.identity;
        if(!expected.world.equals(id.world))return "world_changed";
        if(!expected.player.equals(id.player))return "player_changed";
        if(!expected.session.equals(id.session))return "action_session_changed";
        if(!expected.vehicle.equals(id.vehicle)||expected.vehicleId!=id.vehicleId)return "vehicle_changed";
        if(!expected.passengers.equals(id.passengers))return "passengers_changed";
        if(!sample.driving)return "not_controlling_passenger";
        if(!sample.ordinaryBoat)return "boat_type_unsupported";
        if(!sample.alive)return "vehicle_unavailable";
        if(sample.bubble)return "bubble_column";
        if(!sample.water)return "requires_water_surface";
        if(sample.collision)return "boat_collision";
        if(!Double.isFinite(sample.speed)||sample.speed>BoatSteering.MAX_SPEED)return "boat_speed_unsafe";
        if(!Double.isFinite(sample.verticalSpeed)||Math.abs(sample.verticalSpeed)>.08)return "vertical_motion_unsafe";
        if(!Double.isFinite(sample.y)||sample.y<sample.surfaceY-.8||sample.y>sample.surfaceY-.05)return "water_surface_changed";
        return null;
    }
    private BoatDriveGuard() { }
}
