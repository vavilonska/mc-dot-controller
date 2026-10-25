package io.github.campione01.mineclientbridge;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.protocol.game.ServerboundUseItemOnPacket;
import net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
/** Real vanilla argument objects and production readers; no world, server, native effect or Mixin. */
public final class TypedItemArgumentNativeChecks {
    private static int checks;
    private static final Method PACKET_READER=packetReader();
    private static final class CallbackHit extends BlockHitResult {
        int calls;
        CallbackHit(){super(new Vec3(.5,64,.5),Direction.UP,new BlockPos(0,63,0),false);}
        @Override public BlockPos getBlockPos(){calls++;throw new AssertionError("nested callback invoked");}
    }
    private static Method packetReader(){try{var m=ScopedItemInteraction.class.getDeclaredMethod("packetIdentity",ServerboundUseItemOnPacket.class);m.setAccessible(true);return m;}catch(ReflectiveOperationException failure){throw new IllegalStateException(failure);}}
    private static PlacementPacketBinding binding(ServerboundUseItemOnPacket packet){
        try{return (PlacementPacketBinding)PACKET_READER.invoke(null,packet);}
        catch(InvocationTargetException failed){if(failed.getCause() instanceof RuntimeException runtime)throw runtime;throw new AssertionError(failed.getCause());}
        catch(ReflectiveOperationException failed){throw new IllegalStateException(failed);}
    }
    private static TypedBoundaryPolicy packetFrame(ServerboundUseItemOnPacket packet){
        var b=binding(packet);var h=packet.getHitResult();return new TypedBoundaryPolicy(new Object[]{packet,packet.getHand(),h,h.getBlockPos(),h.getLocation(),h.getDirection(),h.getType()},
            new long[]{b.sequence(),b.x(),b.y(),b.z(),Double.doubleToLongBits(b.hitX()),Double.doubleToLongBits(b.hitY()),Double.doubleToLongBits(b.hitZ()),b.inside()?1:0});
    }
    private static UseOnContext context(BlockHitResult hit){
        try{
            var c=UseOnContext.class.getDeclaredConstructor(net.minecraft.world.level.Level.class,net.minecraft.world.entity.player.Player.class,InteractionHand.class,net.minecraft.world.item.ItemStack.class,BlockHitResult.class);
            c.setAccessible(true);return c.newInstance(null,null,InteractionHand.MAIN_HAND,null,hit);
        }catch(ReflectiveOperationException failed){throw new IllegalStateException(failed);}
    }
    private static TypedBoundaryPolicy contextFrame(UseOnContext context){
        var hit=TypedPortalReaders.contextHit(context);return new TypedBoundaryPolicy(new Object[]{context,hit,hit.getBlockPos(),hit.getLocation(),context.getHand(),context.getItemInHand()},new long[0]);
    }
    private static BlockHitResult hit(){return new BlockHitResult(new Vec3(.5,64,.5),Direction.UP,new BlockPos(0,63,0),false);}
    private static void mutate(Class<?> owner,Object object,String name,Object value){try{var f=owner.getDeclaredField(name);f.setAccessible(true);f.set(object,value);}catch(ReflectiveOperationException failed){throw new IllegalStateException(failed);}}
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    private static void fails(Runnable call){try{call.run();throw new AssertionError("expected refusal");}catch(IllegalStateException expected){checks++;}}
    public static void main(String[] args){
        for(int change=0;change<8;change++){
            BlockHitResult hit=hit();var packet=new ServerboundUseItemOnPacket(InteractionHand.MAIN_HAND,hit,7);var fence=new ItemInteractionArgumentFence();int selected=change;int[] charges={0};
            fails(()->{fence.check(()->{
                switch(selected){
                    case 0 -> mutate(ServerboundUseItemOnPacket.class,packet,"hand",InteractionHand.OFF_HAND);
                    case 1 -> mutate(ServerboundUseItemOnPacket.class,packet,"sequence",8);
                    case 2 -> mutate(ServerboundUseItemOnPacket.class,packet,"blockHit",hit());
                    case 3 -> mutate(BlockHitResult.class,hit,"direction",Direction.DOWN);
                    case 4 -> mutate(BlockHitResult.class,hit,"blockPos",new BlockPos(0,63,0));
                    case 5 -> mutate(HitResult.class,hit,"location",new Vec3(.5,64,.5));
                    case 6 -> mutate(BlockHitResult.class,hit,"inside",true);
                    case 7 -> mutate(BlockHitResult.class,hit,"miss",true);
                }
            },()->packetFrame(packet));charges[0]++;});check(charges[0]==0);
            fails(()->fence.check(()->charges[0]++,()->packetFrame(packet)));check(charges[0]==0);
        }
        var good=new ServerboundUseItemOnPacket(InteractionHand.MAIN_HAND,hit(),7);new ItemInteractionArgumentFence().check(()->{},()->packetFrame(good));check(binding(good).sequence()==7);
        var selection=new ServerboundSetCarriedItemPacket(2);var selectionFence=new ItemInteractionArgumentFence();
        fails(()->selectionFence.check(()->mutate(ServerboundSetCarriedItemPacket.class,selection,"slot",3),()->new TypedBoundaryPolicy(new Object[]{selection},new long[]{selection.getSlot()})));
        var original=hit();var use=context(original);check(TypedPortalReaders.contextHit(use)==original);
        fails(()->new ItemInteractionArgumentFence().check(()->mutate(UseOnContext.class,use,"hitResult",hit()),()->contextFrame(use)));
        var callback=new CallbackHit();var badPacket=new ServerboundUseItemOnPacket(InteractionHand.MAIN_HAND,callback,7);
        fails(()->binding(badPacket));check(callback.calls==0);
        var badContext=context(callback);fails(()->TypedPortalReaders.contextHit(badContext));check(callback.calls==0);
        fails(()->TypedPortalReaders.contextHit(null));
        System.out.println("typed item real argument/reader checks: "+checks+" passed");
    }
}
