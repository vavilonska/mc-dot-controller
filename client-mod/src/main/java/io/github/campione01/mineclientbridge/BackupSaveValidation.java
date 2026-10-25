package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import com.mojang.serialization.Codec;
import com.mojang.serialization.JsonOps;
import java.io.IOException;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import net.minecraft.nbt.*;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.PlayerAdvancements;
import net.minecraft.stats.ServerStatsCounter;
import net.minecraft.world.level.chunk.storage.SectionStorage;
import net.minecraft.world.level.chunk.storage.SimpleRegionStorage;
import net.neoforged.neoforge.common.IOUtilities;
import org.apache.logging.log4j.Level;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.LoggerContext;
import org.apache.logging.log4j.core.appender.AbstractAppender;
import org.apache.logging.log4j.core.config.Property;

/** Version-pinned, read-only validation and drain of the fixed vanilla/NeoForge writer set. */
final class BackupSaveValidation {
    record Capture(String uuid,CompoundTag player,JsonElement stats,JsonElement advancements,long gameTime,int tick) { }
    static Capture capture(MinecraftServer server,ServerPlayer p) throws Exception {
        CompoundTag tag=p.saveWithoutId(new CompoundTag());
        Method stats=ServerStatsCounter.class.getDeclaredMethod("toJson");stats.setAccessible(true);
        JsonElement sj=JsonParser.parseString((String)stats.invoke(p.getStats()));
        Object adv=p.getAdvancements();
        Method data=PlayerAdvancements.class.getDeclaredMethod("asData");data.setAccessible(true);
        Field codec=PlayerAdvancements.class.getDeclaredField("codec");codec.setAccessible(true);
        @SuppressWarnings("unchecked") Codec<Object> c=(Codec<Object>)codec.get(adv);
        JsonElement aj=c.encodeStart(JsonOps.INSTANCE,data.invoke(adv)).getOrThrow();
        return new Capture(p.getStringUUID(),tag,sj,aj,server.overworld().getGameTime(),server.getTickCount());
    }
    static void requireSettledChunks(MinecraftServer server) throws Exception {
        // saveAllChunks uses managedBlock: refuse unresolved generation/unload work rather than
        // pumping unrelated queued gameplay tasks inside the intended simulation barrier.
        Class<?> type=net.minecraft.server.level.ChunkMap.class;
        Field updating=type.getDeclaredField("updatingChunkMap");updating.setAccessible(true);
        Field visible=type.getDeclaredField("visibleChunkMap");visible.setAccessible(true);
        Field pending=type.getDeclaredField("pendingUnloads");pending.setAccessible(true);
        Field unloading=type.getDeclaredField("unloadQueue");unloading.setAccessible(true);
        Field dropping=type.getDeclaredField("toDrop");dropping.setAccessible(true);
        for(var level:server.getAllLevels()) {
            var map=level.getChunkSource().chunkMap;
            require(!level.getChunkSource().getLightEngine().hasLightWork(),"backup_chunk_lighting_pending");
            require(((java.util.Map<?,?>)pending.get(map)).isEmpty() && ((java.util.Queue<?>)unloading.get(map)).isEmpty()
                && ((it.unimi.dsi.fastutil.longs.LongSet)dropping.get(map)).isEmpty(),"backup_chunk_unloads_pending");
            Set<Object> holders=java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
            holders.addAll(((java.util.Map<?,?>)updating.get(map)).values());holders.addAll(((java.util.Map<?,?>)visible.get(map)).values());
            for(Object value:holders) {
                var holder=(net.minecraft.server.level.ChunkHolder)value;
                require(holder.isReadyForSaving() && holder.getGenerationRefCount()==0,"backup_chunk_generation_pending");
            }
        }
    }
    static void drainPoiAndSavedData(MinecraftServer server) throws Exception {
        Field storage=SectionStorage.class.getDeclaredField("simpleRegionStorage");storage.setAccessible(true);
        for(var level:server.getAllLevels()) {
            var poi=level.getPoiManager();
            poi.tick(()->true); // Serialize every dirty POI column, not just those paired with dirty chunks.
            ((SimpleRegionStorage)storage.get(poi)).synchronize(true).join();
        }
        IOUtilities.waitUntilIOWorkerComplete(); // NeoForge SavedData has a different queue from POI.
    }
    static JsonObject validate(Path world,MinecraftServer server,ServerPlayer p,Capture before) throws Exception {
        Capture after=capture(server,p);
        CompoundTag expected=server.getWorldData().createTag(server.registryAccess(),server.getPlayerList().getSingleplayerData());
        return validateSavedFiles(world,before,after,expected);
    }
    static JsonObject validateSavedFiles(Path world,Capture before,Capture after,CompoundTag expected) throws Exception {
        require(before.tick()==after.tick() && before.gameTime()==after.gameTime(),"simulation_advanced_during_snapshot");
        require(before.player().equals(after.player()),"player_changed_in_save_hook");
        require(before.stats().equals(after.stats()) && before.advancements().equals(after.advancements()),"progress_changed_in_save_hook");
        require(readNbt(world.resolve("playerdata/"+before.uuid()+".dat")).equals(before.player()),"saved_player_mismatch");
        require(json(world.resolve("stats/"+before.uuid()+".json")).equals(before.stats()),"saved_stats_mismatch");
        require(json(world.resolve("advancements/"+before.uuid()+".json")).equals(before.advancements()),"saved_advancements_mismatch");
        CompoundTag actual=readNbt(world.resolve("level.dat")).getCompound("Data");
        expected=expected.copy();expected.remove("LastPlayed");actual.remove("LastPlayed");
        // NeoForge appends additional root metadata; every captured vanilla Data field must agree exactly.
        for(String key:expected.getAllKeys())require(Objects.equals(actual.get(key),expected.get(key)),"saved_level_mismatch:"+key);
        require(actual.contains("Player",10) && actual.getCompound("Player").equals(before.player()),"level_player_mismatch");
        int parsed=0;
        try(var paths=Files.walk(world)) {
            for(Path file:paths.filter(Files::isRegularFile).toList()) {
                String name=file.getFileName().toString();
                if(name.endsWith(".json")){json(file);parsed++;}
                else if(name.endsWith(".dat")||name.endsWith(".dat_old")){readNbt(file);parsed++;}
            }
        }
        JsonObject j=new JsonObject();j.addProperty("player_nbt_exact",true);j.addProperty("level_fields_exact",true);
        j.addProperty("stats_exact",true);j.addProperty("advancements_exact",true);j.addProperty("parsed_data_files",parsed);
        j.addProperty("server_tick",before.tick());j.addProperty("game_time",before.gameTime());
        return j;
    }
    static CompoundTag readNbt(Path path) throws IOException {return NbtIo.readCompressed(path,NbtAccounter.create(128L*1024*1024));}
    static JsonElement json(Path path) throws IOException {try(var r=Files.newBufferedReader(path)){JsonElement j=JsonParser.parseReader(r);require(j.isJsonObject(),"non_object_json:"+path.getFileName());return j;}}
    static void require(boolean condition,String reason)throws IOException {if(!condition)throw new IOException(reason);}

    /** Save APIs swallow exceptions; observe their synchronous logging as an independent failure channel. */
    static final class Errors extends AbstractAppender implements AutoCloseable {
        private final List<String> failures=new CopyOnWriteArrayList<>();
        private final boolean persistent;
        private final List<org.apache.logging.log4j.core.Logger> attached=new ArrayList<>();
        Errors() throws IOException { this(false); }
        Errors(boolean persistent) throws IOException {
            super("MDC-Backup-"+UUID.randomUUID(),null,null,false,Property.EMPTY_ARRAY);
            this.persistent=persistent;
            Object context=LogManager.getContext(false);
            require(context instanceof LoggerContext,"unsupported_logging_error_channel");
            LoggerContext ctx=(LoggerContext)context;
            // All known save loggers plus root; no settings or production permissions are changed.
            Set<String> names=new LinkedHashSet<>(List.of("","net.minecraft.world.level.storage.PlayerDataStorage",
                "net.minecraft.stats.ServerStatsCounter","net.minecraft.server.PlayerAdvancements",
                "net.minecraft.world.level.storage.LevelStorageSource","net.minecraft.world.level.saveddata.SavedData",
                "net.minecraft.world.level.chunk.storage.IOWorker","net.minecraft.server.level.ChunkMap",
                "net.minecraft.world.level.chunk.storage.SectionStorage","net.minecraft.world.level.chunk.storage.EntityStorage",
                "net.minecraft.server.MinecraftServer","net.neoforged.neoforge.common.IOUtilities"));
            require(warningsAccepted(ctx.getConfiguration().getFilter()),"global_logging_filter_unsupported");
            // Validate before attachment so a failed install cannot leak a half-installed appender.
            for(String name:names){var logger=ctx.getLogger(name);var config=ctx.getConfiguration().getLoggerConfig(name);
                require(!logger.getClass().getName().contains("Async")&&!config.getClass().getName().contains("Async"),"async_save_logging_unsupported");
                require(logger.isWarnEnabled()&&config.getFilter()==null,"save_logging_filtered");}
            start();
            for(String name:names){var logger=ctx.getLogger(name);logger.addAppender(this);attached.add(logger);}
        }
        @Override public void append(LogEvent event){if(event.getLevel().isMoreSpecificThan(Level.WARN)) {
            String message=event.getMessage().getFormattedMessage();String lower=message.toLowerCase(java.util.Locale.ROOT);
            // Long-lived latch only records save/write faults; ordinary lag WARN must not poison it.
            if(persistent && !(lower.contains("sav")||lower.contains("writ")||lower.contains("flush")||lower.contains("store")||lower.contains("synchroniz")||lower.contains("i/o")||lower.contains("ioerror")))return;
            if(failures.size()<64)failures.add(event.getLoggerName()+": "+message);
        }}
        static boolean warningsAccepted(org.apache.logging.log4j.core.Filter filter) {
            if(filter==null)return true;
            if(filter instanceof org.apache.logging.log4j.core.filter.CompositeFilter composite){
                var iterator=composite.iterator();return iterator.hasNext() && warningsAccepted(iterator.next());
            }
            return filter instanceof org.apache.logging.log4j.core.filter.ThresholdFilter threshold
                && Level.WARN.isMoreSpecificThan(threshold.getLevel())
                && threshold.getOnMatch()==org.apache.logging.log4j.core.Filter.Result.ACCEPT;
        }
        void assertClean() throws IOException {
            for(var logger:attached)require(logger.getAppenders().get(getName())==this && logger.isWarnEnabled(),"save_logging_channel_changed");
            require(failures.isEmpty(),"save_log_error_or_warning:"+(failures.isEmpty()?"":failures.getFirst()));
        }
        List<String> messages(){return List.copyOf(failures);}
        @Override public void close(){for(var l:attached)l.removeAppender(this);stop();}
    }
}
