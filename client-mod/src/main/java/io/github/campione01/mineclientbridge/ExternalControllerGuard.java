package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;

/** Fresh read-only final owner fence. Physics drift is deliberately irrelevant. */
final class ExternalControllerGuard {
    static JsonObject snapshot(Minecraft mc) {
        if (!mc.isSameThread() || mc.player==null || mc.level==null)
            throw new IllegalStateException("external_controller_game_thread_context_required");
        return ExternalControllerProof.snapshot(new ExternalControllerProof.Context(mc,mc.player,mc.level,
                ClientActions.session(),WorldGeneration.current(mc.level),mc.player.getUUID().toString(),mc.level.getGameTime()));
    }
    static boolean idle(Minecraft mc) {
        if(!mc.isSameThread() || mc.player==null || mc.level==null)return false;
        var player=mc.player;var level=mc.level;var gameMode=mc.gameMode;var screen=mc.screen;
        var hit=mc.hitResult;var input=player.input;var held=player.getMainHandItem();
        var heldItem=held.getItem();int count=held.getCount(),damage=held.getDamageValue(),slot=player.getInventory().selected;
        double x=player.getX(),y=player.getY(),z=player.getZ();float yaw=player.getYRot(),pitch=player.getXRot();
        boolean paused=mc.isPaused(),focused=mc.isWindowActive();
        String session=ClientActions.session();long revision=ClientActions.externalOwnerRevision();
        JsonObject proof=snapshot(mc);
        // These are local identity/value reads, after the supported read-only API scan.
        // A mismatched UI/aim/item/input/native owner invalidates the proof itself.
        return mc.player==player && mc.level==level && mc.gameMode==gameMode && mc.screen==screen
                && mc.hitResult==hit && player.input==input && player.getMainHandItem()==held
                && held.getItem()==heldItem && held.getCount()==count && held.getDamageValue()==damage
                && player.getInventory().selected==slot && player.getX()==x && player.getY()==y && player.getZ()==z
                && player.getYRot()==yaw && player.getXRot()==pitch && mc.isPaused()==paused && mc.isWindowActive()==focused
                && ClientActions.externalOwnerRevision()==revision && ClientActions.session().equals(session)
                && proof.get("idle_proven").getAsBoolean();
    }
    static void requireIdle(Minecraft mc) {
        if(!idle(mc))throw new ClientActionRequest.Rejected(409,"external_controller_idle_unproven");
    }
    private ExternalControllerGuard() {}
}
