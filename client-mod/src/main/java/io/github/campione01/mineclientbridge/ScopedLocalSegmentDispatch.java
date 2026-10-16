package io.github.campione01.mineclientbridge;

import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.Vec3;

/** One native client tick's owned motion gate, retained across reentrant owner cancellation. */
public final class ScopedLocalSegmentDispatch {
    private static boolean hookSeen;
    private static Gate gate;
    private static final class Gate {
        final ScopedLocalSegmentMovement owner;
        boolean consumed;
        Gate(ScopedLocalSegmentMovement owner){this.owner=owner;}
    }
    static boolean ready(){return hookSeen;}
    static void arm(ScopedLocalSegmentMovement owner){
        if(!hookSeen||gate!=null)throw new ClientActionRequest.Rejected(409,"local_segment_motion_gate_conflict");
        gate=new Gate(owner);
    }
    /** Called before the next native action tick, never used to extend an old token. */
    static void nextTick(){
        Gate previous=gate;gate=null;
        if(previous!=null&&!previous.consumed)
            ClientActions.localSegmentMotionFailed(previous.owner,"local_segment_motion_not_observed");
    }
    /** The real Entity.move HEAD hook runs after the ordinary jump/NeoForge jump callback. */
    public static boolean beforeMove(Entity entity,MoverType type,Vec3 requested){
        if(entity instanceof LocalPlayer)hookSeen=true;
        Gate current=gate;
        if(current==null||entity!=current.owner.player)return true;
        if(current.consumed){
            ClientActions.localSegmentMotionFailed(current.owner,"local_segment_duplicate_move");return false;
        }
        current.consumed=true;
        try {
            if(type!=MoverType.SELF)throw new ClientActionRequest.Rejected(409,"local_segment_nonself_move");
            current.owner.beforeVanillaMove(Minecraft.getInstance(),requested);
            return true;
        } catch(RuntimeException invalid){
            ClientActions.localSegmentMotionFailed(current.owner,ScopedLocalSegmentMovement.rejection(invalid));
            return false;
        }
    }
    private ScopedLocalSegmentDispatch() { }
}
