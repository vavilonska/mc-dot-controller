package io.github.campione01.mineclientbridge;

import java.util.function.Supplier;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.network.protocol.Packet;

/** Dynamic one-use token. No token means legacy vanilla behavior is unchanged. */
public final class ScopedPlacementDispatch {
    private static boolean itemInstalled,packetInstalled,sendInstalled;
    private static final ThreadLocal<ScopedPlacement> CALL=new ThreadLocal<>();
    private ScopedPlacementDispatch(){}
    public static void itemInstalled(){itemInstalled=true;}
    public static void packetInstalled(){packetInstalled=true;}
    public static void sendInstalled(){sendInstalled=true;}
    static boolean ready(){return itemInstalled&&packetInstalled&&sendInstalled&&ScopedMovementEntities.ready();}
    public static void send(Packet<?> packet){ScopedPlacement g=CALL.get();if(g!=null)g.send(packet);}
    static InteractionResult use(ScopedPlacement guard,Supplier<InteractionResult> vanilla){
        ScopedPlacement.require(CALL.get()==null,"placement_recursive_use_forbidden");CALL.set(guard);
        try{InteractionResult result=vanilla.get();guard.afterUse();return result;}
        catch(RuntimeException failure){guard.markUnknown();throw failure;}
        finally{CALL.remove();}
    }
    public static void enterUse(LocalPlayer player,InteractionHand hand,BlockHitResult hit){
        ScopedPlacement g=CALL.get();if(g!=null)g.enterUse(player,hand,hit);
    }
    public static void beforeEffect(BlockItem item,BlockPlaceContext context,BlockState state){
        ScopedPlacement g=CALL.get();if(g!=null)g.beforeEffect(item,context,state);
    }
    public static void packet(Packet<?> packet,LocalPlayer player,InteractionHand hand,BlockHitResult hit,int sequence){
        ScopedPlacement g=CALL.get();if(g!=null)g.packet(packet,player,hand,hit,sequence);
    }
}
