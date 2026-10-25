package io.github.campione01.mineclientbridge;

import java.util.Locale;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundUseItemOnPacket;
import net.minecraft.world.*;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** One captured vanilla use call only. A stop forbids a later claim, not this call's unwind. */
public final class RecoveryMaintenancePlacementDispatch {
    private static boolean itemReady,packetReady,sendReady;
    private static final ThreadLocal<Scope> CALL=new ThreadLocal<>();
    static final class Witness {
        int entered,effects,packets,sends;Object expected;
        void enter(){require(++entered==1,"maintenance_recursive_use");}
        void effect(){require(entered==1&&effects++==0,"maintenance_extra_effect");}
        void packet(Object p){require(entered==1&&p!=null&&packets++==0&&expected==null,"maintenance_extra_packet");expected=p;}
        void send(Object p){require(expected==p&&p!=null&&sends++==0,"maintenance_unexpected_send");expected=null;}
        boolean returned(){return entered==1&&expected==null&&packets==sends&&effects<=packets;}
    }
    static final class Scope {
        final RecoveryInteraction.Capture c;final Witness witness=new Witness();
        Scope(RecoveryInteraction.Capture c){this.c=c;}
    }
    public static void itemInstalled(){itemReady=true;}
    public static void packetInstalled(){packetReady=true;}
    public static void sendInstalled(){sendReady=true;}
    static boolean ready(){return itemReady&&packetReady&&sendReady;}
    static void use(RecoveryInteraction.Capture c){
        require(CALL.get()==null,"maintenance_recursive_use");Scope s=new Scope(c);CALL.set(s);
        try{
            InteractionResult result=c.gameMode.useItemOn(c.player,InteractionHand.MAIN_HAND,c.placementHit);
            require(c.sameCurrentContext()&&result!=null&&s.witness.returned(),"maintenance_use_unaccounted");
            String target=c.level.getBlockState(c.target).is(Blocks.ANDESITE)?"placed":c.level.getBlockState(c.target)==c.blockState?"unchanged":"other";
            c.entry.gameplay="place_"+result.name().toLowerCase(Locale.ROOT)+"_target_"+target;
        }finally{CALL.remove();}
    }
    public static void enterUse(LocalPlayer player,InteractionHand hand,BlockHitResult hit){
        Scope s=CALL.get();if(s==null)return;
        s.witness.enter();
        require(player==s.c.player&&hand==InteractionHand.MAIN_HAND&&hit==s.c.placementHit&&RecoveryMaintenanceV5.placementBinding(s.c),"maintenance_use_binding");
    }
    public static void beforeEffect(BlockItem item,BlockPlaceContext context,BlockState state){
        Scope s=CALL.get();if(s==null)return;var c=s.c;
        s.witness.effect();
        require(item==c.tool.getItem()&&item.getClass()==BlockItem.class
            &&context.getClass()==BlockPlaceContext.class&&context.getLevel()==c.level&&context.getPlayer()==c.player&&context.getHand()==InteractionHand.MAIN_HAND
            &&context.getClickedFace()==c.placementHit.getDirection()&&net.minecraft.world.item.ItemStack.matches(context.getItemInHand(),c.tool)
            &&context.getClickedPos().equals(c.target)&&state==Blocks.ANDESITE.defaultBlockState()
            &&RecoveryMaintenanceV5.placementBinding(c),"maintenance_placement_effect_mismatch");
    }
    public static void packet(Packet<?> packet,LocalPlayer player,InteractionHand hand,BlockHitResult hit,int sequence){
        Scope s=CALL.get();if(s==null)return;var c=s.c;
        require(c.sameCurrentContext()&&player==c.player
            &&hand==InteractionHand.MAIN_HAND&&hit==c.placementHit&&packet instanceof ServerboundUseItemOnPacket,"maintenance_packet_binding");
        var p=(ServerboundUseItemOnPacket)packet;
        require(p.getHand()==hand&&p.getHitResult()==hit&&p.getSequence()==sequence,"maintenance_packet_arguments");s.witness.packet(packet);
    }
    public static void send(Object connection,Packet<?> packet){
        Scope s=CALL.get();if(s==null||!(packet instanceof ServerboundUseItemOnPacket))return;
        require(s.c.sameCurrentContext()&&connection==s.c.connection,"maintenance_send_binding");s.witness.send(packet);
    }
    private static void require(boolean b,String reason){if(!b)throw new IllegalStateException(reason);}
    private RecoveryMaintenancePlacementDispatch(){}
}
