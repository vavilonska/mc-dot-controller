package io.github.campione01.mineclientbridge;

/** Pure checks for the opt-in single step, composed from existing FlatStepCorridor. */
final class CoordinationStepPolicy {
    record State(double x,double y,double z,double yaw,boolean grounded,boolean available,
                 boolean lifecycleAllowed,boolean sprinting,double speed,float health,
                 double width,double depth,double height,int otherEntities) { }
    static boolean ageValid(long now, long sampled) { long age=now-sampled;return age>=0 && age<=800_000_000L; }
    static String check(ClientActionRequest.Point start, ClientActionRequest.Point end,
                        float initialHealth, State state, FlatStepCorridor.CellSource source) {
        if (!state.available()) return "coordination_step_player_unavailable";
        if (!state.lifecycleAllowed() || !state.grounded()) return "coordination_step_lifecycle";
        if (!Float.isFinite(state.health()) || state.health()<initialHealth || state.sprinting()
                || !Double.isFinite(state.speed()) || state.speed()>.35) return "coordination_step_motion_or_damage";
        if (!Double.isFinite(state.width()) || !Double.isFinite(state.depth()) || !Double.isFinite(state.height())
                || state.width()>.62 || state.depth()>.62 || state.height()>1.81)
            return "coordination_step_player_shape";
        double x=state.x(), y=state.y(), z=state.z();
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)
                || Math.abs(y-start.y())>.05 || x<Math.min(start.x(),end.x())-.15
                || x>Math.max(start.x(),end.x())+.15 || z<Math.min(start.z(),end.z())-.15
                || z>Math.max(start.z(),end.z())+.15) return "coordination_step_left_corridor";
        if (state.otherEntities()!=0) return "coordination_step_entity_nearby";
        int floorY=(int)start.y()-1;
        FlatStepCorridor.CellSource strict=(cx,cy,cz)->{
            var c=source.read(cx,cy,cz);
            if (c==null) return null;
            boolean knownId=cy==floorY?CoordinationStepGuard.SUPPORT.contains(c.id()):"minecraft:air".equals(c.id());
            return knownId?c:new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,c.id(),false,false,false,c.fluid(),true);
        };
        // Existing continuous 0.62-wide swept-corridor checks, split only to
        // respect that primitive's <=0.66 movement bound. No endpoint sampling.
        double dx=(end.x()-x)/2, dz=(end.z()-z)/2;
        var pose=new FlatStepCorridor.Pose(x,y,z,state.grounded(),state.yaw());
        if (!FlatStepCorridor.check(pose,dx,dz,strict).clear()) return "coordination_step_terrain_changed";
        var middle=new FlatStepCorridor.Pose(x+dx,y,z+dz,state.grounded(),state.yaw());
        if (!FlatStepCorridor.check(middle,dx,dz,strict).clear()) return "coordination_step_terrain_changed";
        return null;
    }
    static void transfer(Runnable releaseInputs, Runnable revalidate) {
        // Once any key-up/takeover can have occurred, no 4xx/no-effect claim is
        // permitted, even if a reentrant hook throws an ordinary Rejected error.
        try { releaseInputs.run(); revalidate.run(); }
        catch (RuntimeException failure) {
            throw new IllegalStateException("coordination_step_transfer_outcome_unknown",failure);
        }
    }
    private CoordinationStepPolicy() { }
}
