package io.github.campione01.mineclientbridge;

import java.util.List;

/** Four overlapping translated squares cover a .35-half-width conservative motion envelope. */
final class CombatRouteEnvelope {
    static FlatStepCorridor.Result check(FlatStepCorridor.Pose actual,double dx,double dz,
                                         FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> boxes) {
        return check(actual,dx,dz,cells,boxes,null);
    }
    static FlatStepCorridor.Result check(FlatStepCorridor.Pose actual,double dx,double dz,
                                         FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> boxes,
                                         CombatRetreatWindow.Metrics metrics) {
        if (actual==null) return FlatStepCorridor.rejected("not_in_world",null,dx,dz);
        double margin=CombatRouteMotion.ENVELOPE;
        for(double x:new double[]{-margin,margin}) for(double z:new double[]{-margin,margin}) {
            var pose=new FlatStepCorridor.Pose(actual.x()+x,actual.y(),actual.z()+z,actual.onGround(),actual.yaw());
            var body=CombatRetreatWindow.dynamic(pose,dx,dz,boxes,metrics);
            if(!body.clear()) return FlatStepCorridor.rejected(body.reason(),pose,dx,dz);
            var terrain=CombatRetreatWindow.terrain(pose,dx,dz,cells,metrics,CombatRetreatWindow.Stage.ENVELOPE_TERRAIN);
            if(!terrain.clear()) return terrain;
        }
        return new FlatStepCorridor.Result(true,"motion_envelope_clear",actual,dx,dz,null);
    }
    private CombatRouteEnvelope() { }
}
