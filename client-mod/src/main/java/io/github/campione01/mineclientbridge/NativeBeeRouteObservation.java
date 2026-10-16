package io.github.campione01.mineclientbridge;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.animal.Bee;

/** Owning-server-thread, exact pinned Bee data readers. No goals, hive/world reads or AI callbacks. */
final class NativeBeeRouteObservation {
    static NativeLivingSnapshot.BeeRouteState read(Mob mob) { return observe(mob).state(); }
    /** The closed status is diagnostic only; unavailable state remains null. */
    static NativeLivingSnapshot.BeeRouteRead observe(Mob mob) {
        if(mob.getClass()!=Bee.class||mob.getType()!=EntityType.BEE)
            return new NativeLivingSnapshot.BeeRouteRead(null,"not_exact_bee");
        Bee bee=(Bee)mob;
        BlockPos hive=bee.getHivePos(),flower=bee.getSavedFlowerPos();
        // Vanilla pollination stores an exact MutableBlockPos. Both pinned classes inherit Vec3i field getters.
        // Never invoke coordinate readers on any other subclass; copy values on the owning server thread.
        boolean hiveUntrusted=!trustedPosition(hive);
        boolean flowerUntrusted=!trustedPosition(flower);
        if(hiveUntrusted||flowerUntrusted)return new NativeLivingSnapshot.BeeRouteRead(null,
            hiveUntrusted&&flowerUntrusted?"positions_class_untrusted":hiveUntrusted?"hive_position_class_untrusted":"flower_position_class_untrusted");
        return new NativeLivingSnapshot.BeeRouteRead(new NativeLivingSnapshot.BeeRouteState(
            Bee.class.getName(),bee.hasStung(),bee.hasNectar(),position(hive),position(flower)),"observed");
    }
    private static boolean trustedPosition(BlockPos p){return p==null||p.getClass()==BlockPos.class||p.getClass()==BlockPos.MutableBlockPos.class;}
    private static NativeLivingSnapshot.BeePosition position(BlockPos p){return p==null?null:new NativeLivingSnapshot.BeePosition(p.getX(),p.getY(),p.getZ());}
    static JsonObject json(NativeLivingSnapshot.BeeRouteState value){
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("server_class",value.serverClass());
        j.addProperty("has_stung",value.hasStung());j.addProperty("has_nectar",value.hasNectar());
        j.add("hive_pos",position(value.hive()));j.add("flower_pos",position(value.flower()));return j;
    }
    private static com.google.gson.JsonElement position(NativeLivingSnapshot.BeePosition p){
        if(p==null)return JsonNull.INSTANCE;JsonObject j=new JsonObject();j.addProperty("x",p.x());j.addProperty("y",p.y());j.addProperty("z",p.z());return j;
    }
    private NativeBeeRouteObservation(){}
}
