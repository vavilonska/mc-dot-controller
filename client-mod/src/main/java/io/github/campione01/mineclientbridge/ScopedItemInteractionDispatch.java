package io.github.campione01.mineclientbridge;
import java.util.function.Supplier;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.network.protocol.Packet;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
/** Scoped dynamic token spanning vanilla use, local effect, returned packet and final send. */
public final class ScopedItemInteractionDispatch {
    private static boolean flintInstalled,eyeInstalled,useInstalled,packetInstalled,sendInstalled;
    private static final ThreadLocal<ScopedItemInteraction> CALL=new ThreadLocal<>();
    public static void flintInstalled(){flintInstalled=true;}
    public static void eyeInstalled(){eyeInstalled=true;}
    public static void useInstalled(){useInstalled=true;}
    public static void packetInstalled(){packetInstalled=true;}
    public static void sendInstalled(){sendInstalled=true;}
    static boolean ready(){return flintInstalled&&eyeInstalled&&useInstalled&&packetInstalled&&sendInstalled&&ScopedMovementEntities.ready();}
    static InteractionResult use(ScopedItemInteraction g,Supplier<InteractionResult> call){
        ScopedItemInteractionIntent.need(CALL.get()==null,"item_interaction_recursive_dispatch");CALL.set(g);
        try{InteractionResult result=call.get();g.afterUse();return result;}
        catch(RuntimeException failed){g.markUnknown();throw failed;}finally{CALL.remove();}
    }
    public static void enterUse(LocalPlayer p,InteractionHand h,BlockHitResult hit){var g=CALL.get();if(g!=null)g.enterUse(p,h,hit);}
    public static void beforeItemUse(Item i,UseOnContext c){var g=CALL.get();if(g!=null)g.beforeItemUse(i,c);}
    public static void beforeFlintEffect(Item i,UseOnContext c,net.minecraft.world.level.Level level,BlockPos p,BlockState s,int flags){var g=CALL.get();if(g!=null)g.beforeFlintEffect(i,c,level,p,s,flags);}
    public static void itemResult(Item i,UseOnContext c,InteractionResult r){var g=CALL.get();if(g!=null)g.itemResult(i,c,r);}
    public static void packet(Packet<?> p){var g=CALL.get();if(g!=null)g.packet(p);}
    public static void send(Packet<?> p){var g=CALL.get();if(g!=null)g.send(p);}
    private ScopedItemInteractionDispatch(){}
}
