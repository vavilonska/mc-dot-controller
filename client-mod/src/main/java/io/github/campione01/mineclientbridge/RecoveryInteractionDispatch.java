package io.github.campione01.mineclientbridge;

import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundPlayerActionPacket;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.entity.player.Player;

/** Exact dynamic vanilla call witness. Invalidation prevents NEW calls; an entered call unwinds. */
public final class RecoveryInteractionDispatch {
    private static final ThreadLocal<Scope> CALL=new ThreadLocal<>();
    private static boolean clientReady,gameReady,sendReady;
    static final class Scope {
        final RecoveryInteraction.Capture capture;final boolean cleanup;
        Packet<?> expected;int packetCount,removals;
        Scope(RecoveryInteraction.Capture c,boolean cleanup){capture=c;this.cleanup=cleanup;}
    }
    public static void clientInstalled(){clientReady=true;}
    public static void gameInstalled(){gameReady=true;}
    public static void sendInstalled(){sendReady=true;}
    static boolean ready(){return clientReady&&gameReady&&sendReady;}
    static Scope enter(RecoveryInteraction.Capture c,boolean cleanup){
        require(CALL.get()==null,"recursive_native_mining_call");Scope s=new Scope(c,cleanup);CALL.set(s);return s;
    }
    static void exit(Scope s){try{require(CALL.get()==s&&s.expected==null,"unaccounted_native_packet");}finally{CALL.remove();}}
    static void abandon(){CALL.remove();}
    public static boolean suppressVanillaContinue(boolean down){
        return !down&&NativeRecoveryShortInput.suppressMiningAbort();
    }
    private static void identity(Scope s){require(s.capture.sameCurrentContext(),"native_mining_context_changed_inside_call");}
    public static void beforeDestroy(BlockPos pos){Scope s=CALL.get();if(s==null)return;identity(s);require(!s.cleanup&&s.capture.target.equals(pos),"native_mining_target_changed_inside_call");}
    public static void beforeRemoval(BlockState state,Level level,BlockPos pos,Player player){
        Scope s=CALL.get();if(s==null)return;identity(s);
        if(RecoveryMaintenanceV5.profile(s.capture.entry.request.profile())){require(!RecoveryMaintenanceV5.protectedCell(s.capture.player.getBoundingBox(),pos)&&RecoveryMaintenanceV5.safeTnt(s.capture),"maintenance_removal_current_guard");identity(s);}
        require(!s.cleanup&&s.capture.target.equals(pos)&&s.capture.level==level&&s.capture.player==player
            &&state==s.capture.blockState&&level.getBlockState(pos)==state
            &&s.capture.player.getInventory().selected==s.capture.selected
            &&net.minecraft.world.item.ItemStack.matches(s.capture.tool,s.capture.player.getMainHandItem())&&s.removals++==0,"native_mining_removal_mismatch");
    }
    public static void packet(Packet<?> packet,BlockPos pos,Direction face,int sequence,boolean stop){
        Scope s=CALL.get();if(s==null)return;identity(s);
        require(!s.cleanup&&s.capture.target.equals(pos)&&s.capture.face==face,"native_mining_packet_arguments");
        expect(s,packet,stop?ServerboundPlayerActionPacket.Action.STOP_DESTROY_BLOCK:ServerboundPlayerActionPacket.Action.START_DESTROY_BLOCK,face,sequence);
    }
    public static void progressAbort(Packet<?> packet){Scope s=CALL.get();if(s!=null)throw new IllegalStateException("native_mining_unexpected_retarget_abort");}
    public static void abort(Packet<?> packet){Scope s=CALL.get();if(s==null)return;identity(s);require(s.cleanup,"native_mining_unexpected_abort");expect(s,packet,ServerboundPlayerActionPacket.Action.ABORT_DESTROY_BLOCK,Direction.DOWN,0);}
    private static void expect(Scope s,Packet<?> packet,ServerboundPlayerActionPacket.Action action,Direction face,int sequence){
        require(s.expected==null&&s.packetCount==0&&packet instanceof ServerboundPlayerActionPacket,"native_mining_extra_packet");
        var p=(ServerboundPlayerActionPacket)packet;
        require(p.getAction()==action&&p.getPos().equals(s.capture.target)&&p.getDirection()==face&&p.getSequence()==sequence,"native_mining_packet_mismatch");s.expected=packet;
    }
    public static void send(Object connection,Packet<?> packet){
        Scope s=CALL.get();if(s==null||!(packet instanceof ServerboundPlayerActionPacket))return;
        identity(s);require(connection==s.capture.connection&&s.expected==packet,"native_mining_send_mismatch");s.expected=null;s.packetCount++;
    }
    private static void require(boolean value,String reason){if(!value)throw new IllegalStateException(reason);}
    private RecoveryInteractionDispatch(){}
}
