package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.tags.BlockTags;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.common.NeoForge;

/** Client-thread-only read adapter. No packets, world writes, input ownership or server access. */
final class LoadedWorldScanner {
    private static final LinkedHashMap<String, LoadedScan> HISTORY = new LinkedHashMap<>();
    private static LoadedScan active;
    private static ClientLevel activeLevel;
    private static boolean installed;
    private LoadedWorldScanner() { }
    static synchronized void install() {
        if(installed)return;
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class,event->tick());
        installed=true;
    }
    private static Minecraft thread(){Minecraft mc=Minecraft.getInstance();if(!mc.isSameThread())throw new IllegalStateException("Scan requires client thread");return mc;}
    static JsonObject start(LoadedScanRequest request) {
        Minecraft mc=thread();
        LoadedScan prior=HISTORY.get(request.id());
        if(prior!=null){if(!prior.request.equals(request))throw new ClientActionRequest.Rejected(409,"scan_id_conflict");return prior.snapshot(System.currentTimeMillis());}
        if(active!=null)throw new ClientActionRequest.Rejected(409,"scan_busy");
        if(mc.level==null||mc.player==null)throw new ClientActionRequest.Rejected(409,"not_in_world");
        ClientLevel level=mc.level;
        LoadedScanRequest.Bounds b=request.bounds();
        if(b==null){
            // Read only the actual client cache window; never derive or request distant chunks.
            var storage=level.getChunkSource().storage;
            int r=storage.chunkRadius;
            b=new LoadedScanRequest.Bounds((storage.viewCenterX-r)<<4,((storage.viewCenterX+r)<<4)+15,
                    (storage.viewCenterZ-r)<<4,((storage.viewCenterZ+r)<<4)+15,null,null);
        }
        int minY=b.minY()==null?level.getMinBuildHeight():Math.max(b.minY(),level.getMinBuildHeight());
        int maxY=b.maxY()==null?level.getMaxBuildHeight()-1:Math.min(b.maxY(),level.getMaxBuildHeight()-1);
        if(minY>maxY)throw LoadedScanRequest.bad("scan_outside_world_height");
        // A scan started below the world top could confuse cave water with surface water.
        if(request.sites()&&maxY!=level.getMaxBuildHeight()-1)throw LoadedScanRequest.bad("site_scan_requires_world_top");
        b=new LoadedScanRequest.Bounds(b.minX(),b.maxX(),b.minZ(),b.maxZ(),minY,maxY);
        LoadedScanRequest.validateXZ(b);
        active=new LoadedScan(request,b,level.dimension().location().toString(),WorldGeneration.current(level),
                mc.player.getBlockX(),mc.player.getBlockY(),mc.player.getBlockZ(),System.currentTimeMillis(),System::nanoTime);
        activeLevel=level;HISTORY.put(request.id(),active);
        while(HISTORY.size()>4)HISTORY.remove(HISTORY.keySet().iterator().next());
        return active.snapshot(System.currentTimeMillis());
    }
    static JsonObject status(String id){thread();LoadedScan scan=HISTORY.get(id);if(scan==null)throw new ClientActionRequest.Rejected(404,"scan_not_found");return scan.snapshot(System.currentTimeMillis());}
    static JsonObject cancel(String id){thread();LoadedScan scan=HISTORY.get(id);if(scan==null)throw new ClientActionRequest.Rejected(404,"scan_not_found");if(scan==active){scan.finish("cancelled","cancel_requested",System.currentTimeMillis());active=null;activeLevel=null;}return scan.snapshot(System.currentTimeMillis());}
    private static void tick(){
        Minecraft mc=thread();if(active==null)return;
        long now=System.currentTimeMillis();
        if(mc.level!=activeLevel||mc.player==null){active.finish("cancelled","world_transition",now);active=null;activeLevel=null;return;}
        try {active.tick(new Source(activeLevel,active.request),now);}
        catch(RuntimeException failure){active.finish("failed","scan_read_failed",now);}
        if(!active.status.equals("running")){active=null;activeLevel=null;}
    }
    private static final class Source implements LoadedScan.Source {
        private final ClientLevel level;
        private final LoadedScanRequest request;
        private final Map<BlockState,LoadedScan.Sample> samples=new IdentityHashMap<>();
        private final Map<Block,String> oreIds=new IdentityHashMap<>();
        private int chunkX=Integer.MIN_VALUE,chunkZ=Integer.MIN_VALUE;
        private LevelChunk chunk;
        private final BlockPos.MutableBlockPos pos=new BlockPos.MutableBlockPos();
        Source(ClientLevel level,LoadedScanRequest request){this.level=level;this.request=request;}
        @Override public boolean loaded(int x,int z){
            if(x!=chunkX||z!=chunkZ){chunkX=x;chunkZ=z;chunk=level.getChunkSource().getChunk(x,z,ChunkStatus.FULL,false);}
            return chunk!=null;
        }
        @Override public boolean emptySection(int x,int y,int z){return !request.oreIds().contains("minecraft:air")&&!request.oreIds().contains("minecraft:cave_air")&&!request.oreIds().contains("minecraft:void_air")&&chunk.getSection(chunk.getSectionIndex(y)).hasOnlyAir();}
        @Override public LoadedScan.Sample block(int x,int y,int z){
            BlockState state=chunk.getBlockState(pos.set(x,y,z));
            LoadedScan.Sample known=samples.get(state);if(known!=null)return known;
            Block block=state.getBlock();String id=oreIds.computeIfAbsent(block,b->BuiltInRegistries.BLOCK.getKey(b).toString());
            String ore=request.ores()&&request.oreIds().contains(id)?id:null;
            boolean water=block==Blocks.WATER||block==Blocks.BUBBLE_COLUMN;
            boolean surface=water||(!state.isAir()&&state.blocksMotion()&&!state.is(BlockTags.LEAVES)&&!state.is(BlockTags.LOGS));
            LoadedScan.Sample sample=new LoadedScan.Sample(ore,surface,water);samples.put(state,sample);return sample;
        }
        @Override public String biome(int x,int y,int z){return chunk.getNoiseBiome(x>>2,y>>2,z>>2).unwrapKey().map(key->key.location().toString()).orElse("unknown");}
    }
}
