package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.AABB;

/** Minecraft adapter; reads only loaded local collision, never moves the player. */
final class NavigationPositionGuard {
    private static final PositionDiscontinuityGuard GUARD=new PositionDiscontinuityGuard();
    private static long tick;
    static boolean applies(String action) {
        return switch(action) {
            case "follow_path", "break_block", "place_block", "combat_entity" -> true;
            default -> false; // Boat steering has its own motion/support contract.
        };
    }
    static void tick(Minecraft mc) { tick++; observe(mc); }
    static void observe(Minecraft mc) {
        try { observeLoadedState(mc); }
        catch (RuntimeException unavailable) {
            // An observation failure must never keep an old route authorized.
            GUARD.sample(mc.level,mc.player,new PositionDiscontinuityGuard.Sample(
                    Double.NaN,0,0,0,0,0,false,false,false,false),tick);
        }
    }
    private static void observeLoadedState(Minecraft mc) {
        if (mc.player==null || mc.level==null) { GUARD.sample(mc.level,mc.player,null,tick); return; }
        var p=mc.player; var v=p.getDeltaMovement(); AABB box=p.getBoundingBox();
        boolean loaded=true;
        for (BlockPos cell:BlockPos.betweenClosed(BlockPos.containing(box.minX-.1,box.minY-.2,box.minZ-.1),
                BlockPos.containing(box.maxX+.1,box.maxY+.1,box.maxZ+.1))) {
            if (!mc.level.hasChunkAt(cell)) { loaded=false; break; }
        }
        boolean supported=loaded && !mc.level.noCollision(p,box.move(0,-.08,0));
        GUARD.sample(mc.level,p,new PositionDiscontinuityGuard.Sample(p.getX(),p.getY(),p.getZ(),
                v.x,v.y,v.z,p.onGround(),loaded,supported,p.isPassenger()),tick);
    }
    static long epoch() { return GUARD.epoch(); }
    static void requireBinding(Minecraft mc, ClientActionRequest request) {
        observe(mc);
        if (applies(request.action())) GUARD.requireBinding(request.original());
    }
    static JsonObject snapshot(Minecraft mc) { observe(mc); return GUARD.snapshot(); }
    private NavigationPositionGuard() { }
}
