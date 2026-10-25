package io.github.campione01.mineclientbridge;

import net.minecraft.world.phys.AABB;

/** Focused policy tests, not a substitute for the server's actual wall ray in TEST. */
public final class BackupThreatChecks {
    private static int checks;
    private static void expect(String expected,boolean target,boolean enemy,boolean projectile,
            boolean visible,boolean contact,double distance,String name) {
        String actual=NativeWorldBackup.threatReason(target,enemy,projectile,visible,contact,distance);
        if(!java.util.Objects.equals(expected,actual))throw new AssertionError(name+":"+actual);
        checks++;
    }
    public static void main(String[] args) {
        expect(null,false,true,false,false,false,100,"same32m_behind_wall_no_target_allowed");
        expect(null,false,true,false,false,false,1,"near_other_floor_no_contact_no_target_allowed");
        expect("visible_hostile",false,true,false,true,false,100,"wall_removed_visible_hostile_refused");
        expect("target_self",true,true,false,false,false,400,"actual_aggro_behind_wall_refused");
        expect("target_self",true,false,false,false,false,400,"nonEnemy_real_target_refused");
        expect(null,false,false,false,true,false,1,"passive_nearby_allowed");
        expect("close_contact",false,true,false,false,true,.1,"touching_hostile_refused");
        expect("close_contact",false,false,true,false,true,.1,"touching_projectile_refused");
        expect("visible_projectile",false,false,true,true,false,256,"visible_projectile_16m_refused");
        expect(null,false,false,true,false,false,16,"occluded_projectile_no_contact_allowed");
        expect(null,false,false,true,true,false,257,"distant_projectile_outside_near_policy");
        expect("visible_hostile",false,true,false,true,false,1024,"hostile_32m_boundary");
        expect(null,false,true,false,true,false,1025,"visible_hostile_outside_32m_no_aggro");
        expect("invalid_threat_position",false,true,false,false,false,Double.NaN,"nonfinite_refused");
        AABB player=new AABB(0,0,0,.6,1.8,.6);
        boolean bodyNear=player.inflate(.2).intersects(new AABB(.75,0,0,1.35,1.8,.6));
        boolean wallSeparated=player.inflate(.2).intersects(new AABB(1.6,0,0,2.2,1.8,.6));
        expect("close_contact",false,true,false,false,bodyNear,1,"actual_AABB_touching");
        expect(null,false,true,false,false,wallSeparated,4,"actual_AABB_full_wall_gap");
        System.out.println("BackupThreatChecks PASS "+checks+"; real LOS/server target acquisition live TEST NOT_RUN");
    }
}
