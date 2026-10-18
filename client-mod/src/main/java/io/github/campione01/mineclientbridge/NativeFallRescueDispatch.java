package io.github.campione01.mineclientbridge;

import java.util.function.Supplier;
import net.minecraft.core.BlockPos;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundUseItemPacket;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.BlockHitResult;

/** Dynamic call-stack token survives cancellation until vanilla useItem unwinds. */
public final class NativeFallRescueDispatch {
    private static boolean bucketInstalled,sendInstalled;
    private static final ThreadLocal<Object> CALL=new ThreadLocal<>();
    public static void bucketInstalled(){bucketInstalled=true;}
    public static void sendInstalled(){sendInstalled=true;}
    static boolean ready(){return bucketInstalled&&sendInstalled;}
    static InteractionResult use(Object token,Supplier<InteractionResult> vanilla){
        if(CALL.get()!=null)throw new IllegalStateException("fall_rescue_recursive_use_forbidden");
        CALL.set(token);try{return vanilla.get();}finally{CALL.remove();}
    }
    public static void bucket(Object bucket,Player player,Level level,BlockPos target,BlockHitResult hit,ItemStack stack,boolean finalEffect){
        Object token=CALL.get();if(token!=null)NativeFallRescue.bucketEffect(token,bucket,player,level,target,hit,stack,finalEffect);
    }
    public static void send(Packet<?> packet){
        Object token=CALL.get();if(token!=null&&packet instanceof ServerboundUseItemPacket use)NativeFallRescue.packet(token,use);
    }
    private NativeFallRescueDispatch() { }
}
