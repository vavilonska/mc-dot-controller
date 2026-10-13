package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.*;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import net.minecraft.SharedConstants;
import net.minecraft.client.multiplayer.ClientChunkCache;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.core.BlockPos;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import net.minecraft.world.phys.shapes.CollisionContext;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;

/** Genuine FML registries and block callbacks with finite read-only level shells.
 * No game, world constructor, server, player, packet, lighting engine or physics loop runs. */
@EnabledIfEnvironmentVariable(named = "MDC_REAL_MOD_LOADER_TESTS", matches = "true")
@Execution(ExecutionMode.SAME_THREAD)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class TerrainCapabilityLoaderTest {
    @BeforeAll static void bootstrap() { SharedConstants.tryDetectVersion(); Bootstrap.bootStrap(); }
    static final class LevelShell extends ClientLevel {
        CacheShell cache;
        private LevelShell() { super(null, null, null, null, 0, 0, () -> null, null, false, 0); throw new AssertionError("Allocation only"); }
        @Override public ClientChunkCache getChunkSource() { return cache; }
        @Override public int getMinBuildHeight() { return -64; }
        @Override public int getHeight() { return 384; }
        @Override public int getBrightness(LightLayer layer, BlockPos pos) { return layer == LightLayer.SKY ? 15 : 0; }
        @Override public BlockState getBlockState(BlockPos pos) { throw new AssertionError("Never use a live level block accessor"); }
    }
    static final class CacheShell extends ClientChunkCache {
        ChunkShell chunk; boolean missing; int lookups;
        private CacheShell() { super(null, 0); throw new AssertionError("Allocation only"); }
        @Override public LevelChunk getChunk(int x, int z, ChunkStatus status, boolean create) {
            assertSame(ChunkStatus.FULL, status); assertFalse(create); lookups++;
            return missing ? null : chunk;
        }
    }
    static final class ChunkShell extends LevelChunk {
        BlockState state; int reads;
        private ChunkShell() { super(null, null); throw new AssertionError("Allocation only"); }
        @Override public BlockState getBlockState(BlockPos pos) { reads++; return state; }
        @Override public BlockState setBlockState(BlockPos pos, BlockState state, boolean moving) { throw new AssertionError("No writes"); }
    }
    static <T> T allocate(Class<T> type) throws Exception {
        Field field = sun.misc.Unsafe.class.getDeclaredField("theUnsafe"); field.setAccessible(true);
        return type.cast(((sun.misc.Unsafe) field.get(null)).allocateInstance(type));
    }
    static LevelShell level() throws Exception {
        var level = allocate(LevelShell.class); level.cache = allocate(CacheShell.class); level.cache.chunk = allocate(ChunkShell.class);
        level.cache.chunk.state = Blocks.STONE.defaultBlockState(); return level;
    }
    @SuppressWarnings("unchecked")
    static TerrainScan.Source<JsonObject> loadedSource(LevelShell level) throws Exception {
        Class<?> type = Class.forName("io.github.campione01.mineclientbridge.TerrainReader$LoadedSource");
        Constructor<?> constructor = type.getDeclaredConstructor(ClientLevel.class, CollisionContext.class); constructor.setAccessible(true);
        return (TerrainScan.Source<JsonObject>) constructor.newInstance(level, CollisionContext.empty());
    }

    @Test void genuineLoadedSourceUsesRealVanillaFactsAndLargerBoundedReaderHttpPage() throws Exception {
        var level = level(); var scan = new TerrainScan<JsonObject>(() -> 0L);
        var page = scan.page(TerrainQuery.parse("radius=4&vertical=4&limit=1024&capability=1"), level, 12, 64, 25, loadedSource(level));
        assertTrue(page.cells().size() > 128); assertTrue(page.cells().size() < 729); assertTrue(page.payloadBudgetExhausted());
        assertEquals(page.cells().size() + 1, level.cache.chunk.reads, "Only the unpublished boundary cell is reread later");
        var exchange = TerrainCapabilityWireTest.http(TerrainCapabilityWireTest.pageJson(page));
        assertEquals(200, exchange.status); assertTrue(exchange.bytes.size() < 256 * 1024);
        for (var row : exchange.body().getAsJsonArray("cells")) {
            JsonObject cell = row.getAsJsonObject(); assertEquals("minecraft:stone", cell.get("id").getAsString());
            assertEquals("minecraft:empty", cell.get("fluid").getAsString()); assertTrue(cell.get("collision_known").getAsBoolean());
            assertTrue(cell.get("full_top_support").getAsBoolean()); assertFalse(cell.get("collision_empty").getAsBoolean());
            assertEquals(15, cell.get("sky_light").getAsInt()); assertEquals(0, cell.get("block_light").getAsInt());
        }
        assertTrue(level.cache.lookups <= 4, "Loaded chunk cache stays page-local");
    }

    @Test void genuineLoadedSourceDoesNotReadMissingChunksOrOutOfWorldCells() throws Exception {
        var level = level(); level.cache.missing = true;
        var page = new TerrainScan<JsonObject>(() -> 0L).page(TerrainQuery.parse("capability=1&limit=1024"), level, 0, -64, 0, loadedSource(level));
        assertEquals(1024, page.cells().size()); assertEquals(0, level.cache.chunk.reads);
        assertTrue(page.cells().stream().allMatch(cell -> cell.data() == null));
        var body = TerrainCapabilityWireTest.http(TerrainCapabilityWireTest.pageJson(page)).body();
        assertEquals(1024, body.get("unknown_cells").getAsInt());
        for (var row : body.getAsJsonArray("cells")) { assertFalse(row.getAsJsonObject().get("known").getAsBoolean()); assertFalse(row.getAsJsonObject().has("id")); }
    }

    @Test @Order(1) void realNanoTimeColdAndWarmMeasurementsPreserveAllPagesWithoutLatencyClaims() throws Exception {
        var reports = new JsonArray();
        for (int iteration = 0; iteration < 3; iteration++) {
            var level = level(); var scan = new TerrainScan<JsonObject>(System::nanoTime); var pages = new JsonArray();
            TerrainQuery query = TerrainQuery.parse("radius=4&vertical=4&limit=1024&capability=1");
            int cells = 0; long started = System.nanoTime(); long sleepNanos = 0;
            while (true) {
                var actualSource = loadedSource(level); long[] sizing = new long[2];
                var measuredSource = new TerrainScan.Source<JsonObject>() {
                    public TerrainScan.Availability availability(int x, int y, int z) { return actualSource.availability(x, y, z); }
                    public JsonObject readLoaded(int x, int y, int z) { return actualSource.readLoaded(x, y, z); }
                    public int encodedCellBytes(TerrainScan.Cell<JsonObject> cell) {
                        long before = System.nanoTime();
                        try { return actualSource.encodedCellBytes(cell); }
                        finally { sizing[0] += System.nanoTime() - before; sizing[1]++; }
                    }
                };
                var page = scan.page(query, level, 12, 64, 25, measuredSource);
                assertEquals(cells, page.offset()); cells += page.cells().size();
                var exchange = TerrainCapabilityWireTest.http(TerrainCapabilityWireTest.pageJson(page)); assertEquals(200, exchange.status);
                var record = new JsonObject(); record.addProperty("returned", page.cells().size()); record.addProperty("read_elapsed_nanos", page.elapsedNanos());
                record.addProperty("http_bytes", exchange.bytes.size()); record.addProperty("budget_exhausted", page.budgetExhausted());
                record.addProperty("cell_sizing_nanos", sizing[0]); record.addProperty("cell_sizing_calls", sizing[1]);
                record.addProperty("payload_budget_exhausted", page.payloadBudgetExhausted()); pages.add(record);
                if (page.nextCursor() == null) break;
                query = TerrainQuery.parse("cursor=" + page.nextCursor());
                long before = System.nanoTime(); Thread.sleep(50); sleepNanos += System.nanoTime() - before;
            }
            assertEquals(729, cells);
            var report = new JsonObject(); report.addProperty("iteration", iteration); report.addProperty("phase", iteration == 0 ? "first_measured_scan" : "warm_scan");
            report.addProperty("total_elapsed_nanos", System.nanoTime() - started); report.addProperty("page_sleep_nanos", sleepNanos);
            report.addProperty("cell_reads_including_discarded_boundary", level.cache.chunk.reads); report.add("pages", pages); reports.add(report);
        }
        var root = new JsonObject(); root.addProperty("synthetic_level_shell_not_live_latency_evidence", true);
        root.addProperty("genuine_loader_block_callbacks", true); root.addProperty("clock", "System.nanoTime");
        root.addProperty("first_test_in_class_after_genuine_loader_bootstrap", true);
        root.addProperty("test_wrapper_times_sizing_inside_page_budget", true); root.add("measurements", reports);
        Files.writeString(Path.of(System.getProperty("mineclientBridge.projectDir"), "build", "terrain-capability-timing.json"),
                new GsonBuilder().setPrettyPrinting().create().toJson(root));
    }
}
