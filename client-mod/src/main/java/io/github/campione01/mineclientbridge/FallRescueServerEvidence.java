package io.github.campione01.mineclientbridge;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import net.minecraft.core.BlockPos;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.chunk.status.ChunkStatus;

/** Bounded read-only evidence: never blocks the client and never reads server entities off-thread. */
final class FallRescueServerEvidence {
    record Sample(String episode,BlockPos target,int tick,boolean valid,boolean air,boolean water,
                  boolean waterBucket,boolean emptyBucket,boolean alive,boolean landed,float health) { }
    private final AtomicBoolean pending=new AtomicBoolean();
    private final AtomicReference<Sample> latest=new AtomicReference<>();
    Sample latest(){return latest.get();}
    void request(MinecraftServer server,ResourceKey<Level> dimension,UUID playerId,int slot,BlockPos target,String episode){
        if(!pending.compareAndSet(false,true))return;
        try{server.execute(()->{
            try{
                var level=server.getLevel(dimension);var player=server.getPlayerList().getPlayer(playerId);
                boolean valid=server instanceof net.minecraft.client.server.IntegratedServer integrated&&!integrated.isPublished()&&server.getPlayerCount()==1&&level!=null&&player!=null
                    &&player.serverLevel()==level&&level.getChunkSource().getChunk(target.getX()>>4,target.getZ()>>4,ChunkStatus.FULL,false)!=null;
                if(!valid){latest.set(new Sample(episode,target,server.getTickCount(),false,false,false,false,false,false,false,0));return;}
                var state=level.getBlockState(target);var held=player.getInventory().getItem(slot);
                boolean alive=player.isAlive()&&!player.isDeadOrDying()&&player.getHealth()>0;
                boolean inLandingCell=player.getX()>target.getX()-.1&&player.getX()<target.getX()+1.1
                    &&player.getZ()>target.getZ()-.1&&player.getZ()<target.getZ()+1.1
                    &&player.getY()>=target.getY()-.1&&player.getY()<=target.getY()+1.2;
                boolean landed=alive&&inLandingCell&&(player.onGround()||(player.isInWater()&&Math.abs(player.getDeltaMovement().y)<.3));
                latest.set(new Sample(episode,target,server.getTickCount(),true,FallRescueGeometry.air(state),
                    state.getFluidState().is(FluidTags.WATER)&&state.getFluidState().isSource(),
                    held.is(Items.WATER_BUCKET)&&held.getCount()==1,held.is(Items.BUCKET)&&held.getCount()==1,alive,landed,player.getHealth()));
            }catch(RuntimeException failure){latest.set(new Sample(episode,target,server.getTickCount(),false,false,false,false,false,false,false,0));}
            finally{pending.set(false);}
        });}catch(RuntimeException failure){pending.set(false);throw failure;}
    }
}
