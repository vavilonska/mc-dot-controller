package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;

/** Actual loaded 3x3 two-high roof; no shelter inference from item names or recipes. */
final class CapabilityShelter {
    static boolean safe(Minecraft mc) {
        if(mc.player==null||mc.level==null||!mc.player.onGround())return false;
        BlockPos feet=mc.player.blockPosition();
        if(Math.abs(mc.player.getY()-feet.getY())>.15 || Math.hypot(mc.player.getX()-feet.getX()-.5,mc.player.getZ()-feet.getZ()-.5)>.25)return false;
        if(!CapabilityPath.standable(mc,feet))return false;
        for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++) {
            BlockPos roof=feet.offset(x,2,z);
            if(!mc.level.hasChunkAt(roof)||!CapabilityPath.support(mc,roof)||!mc.level.getBlockState(roof).isCollisionShapeFullBlock(mc.level,roof))return false;
        }
        return true;
    }
    static JsonObject snapshot(Minecraft mc) {
        var j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("safe",safe(mc));
        if(mc.player!=null)j.addProperty("roof_y",mc.player.blockPosition().getY()+2);
        j.addProperty("loaded_only",true);j.addProperty("roof_width",3);return j;
    }
    private CapabilityShelter(){}
}
