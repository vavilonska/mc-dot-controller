package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.Property;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Loaded-client-chunk adapter. This class does not send packets, force chunks, or write world data. */
final class TerrainReader {
    private static TerrainScan.Page<JsonObject> lastPage;
    private static long sampledGameTime;
    private static final TerrainScan<JsonObject> SCAN = new TerrainScan<>(System::nanoTime);
    private static final Pattern SAFE_PROPERTY = Pattern.compile("[a-zA-Z0-9_.:/-]{1,32}");
    private static final Set<String> CONTACT_HAZARDS = Set.of("minecraft:fire", "minecraft:soul_fire",
            "minecraft:cactus", "minecraft:magma_block", "minecraft:sweet_berry_bush", "minecraft:wither_rose");

    private TerrainReader() { }

    /** Compatibility entry point; callers needing evidence should retain flatStepResult. */
    static boolean flatStepClear(Minecraft mc, double dx, double dz) {
        return flatStepResult(mc, dx, dz).clear();
    }

    /** Fresh client-thread pose and exact continuous square sweep, never cached terrain pages. */
    static FlatStepCorridor.Result flatStepResult(Minecraft mc, double dx, double dz) {
        if (!mc.isSameThread()) throw new IllegalStateException("minecraft_thread_required");
        FlatStepCorridor.Pose pose = mc.player == null ? null : new FlatStepCorridor.Pose(
                mc.player.getX(), mc.player.getY(), mc.player.getZ(), mc.player.onGround(), mc.player.getYRot());
        if (mc.player == null || mc.level == null)
            return FlatStepCorridor.rejected("not_in_world", pose, dx, dz);
        return FlatStepCorridor.check(pose, dx, dz, flatCellSource(mc));
    }

    /** Optional per-source aggregate diagnostics; callers must keep the same client-thread/tick scope. */
    static final class ReadMetrics {
        long stateReads, fluidReads, shapeContextReads;
        long chunkRequests, chunkCacheHits, chunkFetches, loadedCellReads;
        // Nested shape-context state reads also belong to collisionNanos; times are not additive.
        long stateReadNanos, metadataPreflightNanos, fluidHazardNanos, collisionNanos;
    }

    /** Fresh loaded cells for a bounded same-tick hypothetical flat route. Never cached across ticks. */
    static FlatStepCorridor.CellSource flatCellSource(Minecraft mc) {
        return flatCellSource(mc, null);
    }

    static FlatStepCorridor.CellSource flatCellSource(Minecraft mc, ReadMetrics metrics) {
        if (!mc.isSameThread()) throw new IllegalStateException("minecraft_thread_required");
        if (mc.level == null || mc.player == null) throw new IllegalStateException("not_in_world");
        LoadedSource source = new LoadedSource(mc.level, CollisionContext.of(mc.player), metrics);
        return source::readFlatCell;
    }

    static JsonObject read(TerrainQuery query) {
        Minecraft mc = Minecraft.getInstance();
        if (!mc.isSameThread()) throw new IllegalStateException("Terrain reads require the Minecraft thread");
        WorldGeneration.current(mc.level);
        if (mc.level == null || mc.player == null) {
            SCAN.clear();
            throw new TerrainScan.Failure(409, "not_in_world");
        }
        ClientLevel level = mc.level;
        BlockPos origin = mc.player.blockPosition();
        TerrainScan.Page<JsonObject> page = SCAN.page(query, level, origin.getX(), origin.getY(), origin.getZ(),
                new LoadedSource(level, CollisionContext.of(mc.player)));
        if (page != lastPage) { sampledGameTime = level.getGameTime(); lastPage = page; }
        JsonObject obj = new JsonObject();
        obj.addProperty("world_generation", WorldGeneration.current(level));
        obj.addProperty("terrain_schema_version", 1);
        obj.addProperty("dimension", level.dimension().location().toString());
        obj.addProperty("generation", page.generation());
        obj.addProperty("consistency", "live_pages");
        obj.addProperty("game_time", sampledGameTime);
        obj.addProperty("response_game_time", level.getGameTime());
        obj.addProperty("read_only", true);
        obj.addProperty("loaded_chunks_only", true);
        JsonObject originJson = new JsonObject();
        originJson.addProperty("x", page.originX()); originJson.addProperty("y", page.originY()); originJson.addProperty("z", page.originZ());
        obj.add("origin", originJson);
        obj.addProperty("radius", page.radius()); obj.addProperty("vertical", page.vertical());
        obj.addProperty("order", "x_then_z_then_y");
        obj.addProperty("offset", page.offset()); obj.addProperty("next_offset", page.nextOffset());
        obj.addProperty("total_cells", page.total()); obj.addProperty("returned", page.cells().size());
        obj.addProperty("complete", page.nextCursor() == null);
        obj.addProperty("next_cursor", page.nextCursor());
        obj.addProperty("budget_exhausted", page.budgetExhausted());
        obj.addProperty("read_elapsed_micros", page.elapsedNanos() / 1000);
        obj.addProperty("retry_after_ms", TerrainScan.MIN_PAGE_INTERVAL_NANOS / 1_000_000);
        JsonArray cells = new JsonArray();
        int unknown = 0;
        for (TerrainScan.Cell<JsonObject> cell : page.cells()) {
            JsonObject data = cell.data() == null ? new JsonObject() : cell.data().deepCopy();
            data.addProperty("x", cell.x()); data.addProperty("y", cell.y()); data.addProperty("z", cell.z());
            data.addProperty("status", cell.availability().name().toLowerCase(Locale.ROOT));
            if (cell.availability() != TerrainScan.Availability.LOADED) {
                data.addProperty("known", false);
                unknown++;
            }
            cells.add(data);
        }
        obj.addProperty("unknown_cells", unknown);
        obj.add("cells", cells);
        return obj;
    }

    static void clear() { SCAN.clear(); }

    private static final class LoadedSource implements TerrainScan.Source<JsonObject> {
        private final ClientLevel level;
        private final CollisionContext collisionContext;
        private final Map<Long, LevelChunk> chunks = new HashMap<>();
        private final ReadMetrics metrics;

        LoadedSource(ClientLevel level, CollisionContext collisionContext) {
            this(level, collisionContext, null);
        }

        LoadedSource(ClientLevel level, CollisionContext collisionContext, ReadMetrics metrics) {
            this.level = level;
            this.collisionContext = collisionContext;
            this.metrics = metrics;
        }

        private LevelChunk loadedChunk(int x, int z) {
            if (metrics != null) metrics.chunkRequests++;
            long key = ((long) (x >> 4) << 32) | ((z >> 4) & 0xffffffffL);
            if (!chunks.containsKey(key)) {
                if (metrics != null) metrics.chunkFetches++;
                // false is essential: missing client chunks stay unknown. No level.getChunk convenience call.
                chunks.put(key, level.getChunkSource().getChunk(x >> 4, z >> 4, ChunkStatus.FULL, false));
            } else if (metrics != null) {
                metrics.chunkCacheHits++;
            }
            return chunks.get(key);
        }

        @Override public TerrainScan.Availability availability(int x, int y, int z) {
            if (y < level.getMinBuildHeight() || y >= level.getMaxBuildHeight()) return TerrainScan.Availability.OUT_OF_WORLD;
            return loadedChunk(x, z) == null ? TerrainScan.Availability.UNLOADED : TerrainScan.Availability.LOADED;
        }

        private BlockState readBlockState(BlockPos pos) {
            long started = metrics == null ? 0 : System.nanoTime();
            try {
                LevelChunk chunk = loadedChunk(pos.getX(), pos.getZ());
                if (metrics != null) metrics.stateReads++;
                return chunk.getBlockState(pos);
            } finally {
                if (metrics != null) metrics.stateReadNanos += System.nanoTime() - started;
            }
        }

        private BlockFacts readBlock(int x, int y, int z) {
            if (metrics != null) metrics.loadedCellReads++;
            BlockPos pos = new BlockPos(x, y, z);
            BlockState state = readBlockState(pos);
            long started = metrics == null ? 0 : System.nanoTime();
            try {
                String id = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                return new BlockFacts(pos, state, id, state.isAir());
            } finally {
                if (metrics != null) metrics.metadataPreflightNanos += System.nanoTime() - started;
            }
        }

        FlatStepCorridor.Cell readFlatCell(int x, int y, int z) {
            TerrainScan.Availability availability = availability(x, y, z);
            if (availability != TerrainScan.Availability.LOADED) {
                FlatStepCorridor.Availability unavailable = switch (availability) {
                    case OUT_OF_WORLD -> FlatStepCorridor.Availability.OUT_OF_WORLD;
                    case UNLOADED -> FlatStepCorridor.Availability.UNLOADED;
                    default -> FlatStepCorridor.Availability.UNKNOWN;
                };
                return new FlatStepCorridor.Cell(unavailable, null, false, false, false, null, false);
            }
            BlockFacts block = readBlock(x, y, z);
            // Preserve export-hook failures without allocating the legacy export JSON graph.
            // Omitting these callbacks could admit a cell the legacy adapter rejected.
            readProperties(block.state(), null);
            FluidFacts fluid = readFluid(block);
            CollisionFacts collision = readCollision(block);
            return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                    bounded(block.id(), 160), collision.known(), collision.empty(), collision.topFull(),
                    bounded(fluid.id(), 160), fluid.hazards() != 0);
        }

        @Override public JsonObject readLoaded(int x, int y, int z) {
            BlockFacts block = readBlock(x, y, z);
            BlockState state = block.state();
            JsonObject obj = new JsonObject();
            obj.addProperty("known", true);
            obj.addProperty("id", bounded(block.id(), 160));
            obj.addProperty("id_truncated", block.id().length() > 160);
            obj.addProperty("air", block.air());
            JsonObject properties = new JsonObject();
            boolean propertiesTruncated = readProperties(state, properties);
            obj.add("properties", properties);
            obj.addProperty("properties_truncated", propertiesTruncated);
            FluidFacts fluid = readFluid(block);
            obj.addProperty("fluid", bounded(fluid.id(), 160));
            obj.addProperty("fluid_truncated", fluid.id().length() > 160);
            obj.addProperty("fluid_source", fluid.source());
            JsonArray hazards = new JsonArray();
            if ((fluid.hazards() & LAVA) != 0) hazards.add("lava");
            if ((fluid.hazards() & WATER) != 0) hazards.add("water");
            if ((fluid.hazards() & CONTACT_DAMAGE) != 0) hazards.add("contact_damage");
            if ((fluid.hazards() & POWDER_SNOW) != 0) hazards.add("powder_snow");
            if ((fluid.hazards() & SLOWDOWN) != 0) hazards.add("slowdown");
            obj.add("hazards", hazards);
            obj.addProperty("hazards_exhaustive", false);
            CollisionFacts collision = readCollision(block);
            obj.addProperty("collision_known", collision.known());
            if (collision.known()) {
                obj.addProperty("collision_empty", collision.empty());
                obj.addProperty("full_top_support", collision.topFull());
                AABB bounds = collision.bounds();
                if (bounds != null) {
                    JsonArray box = new JsonArray();
                    box.add(bounds.minX); box.add(bounds.minY); box.add(bounds.minZ);
                    box.add(bounds.maxX); box.add(bounds.maxY); box.add(bounds.maxZ);
                    obj.add("collision_bounds", box);
                }
            } else {
                obj.addProperty("collision_unknown_reason", collision.unknownReason());
            }
            return obj;
        }

        /** Keep property callback order/failure behavior even when only typed safety facts are needed. */
        private boolean readProperties(BlockState state, JsonObject properties) {
            long started = metrics == null ? 0 : System.nanoTime();
            try {
                int count = 0;
                boolean propertiesTruncated = state.getValues().size() > 8;
                for (Map.Entry<Property<?>, Comparable<?>> property : state.getValues().entrySet()) {
                    if (count++ == 8) break;
                    String name = property.getKey().getName();
                    String value = propertyName(property.getKey(), property.getValue());
                    // Keep pathological mod strings from multiplying escaped JSON beyond the response cap.
                    if (!SAFE_PROPERTY.matcher(name).matches() || !SAFE_PROPERTY.matcher(value).matches()) {
                        propertiesTruncated = true;
                        continue;
                    }
                    if (properties != null) properties.addProperty(name, value);
                }
                return propertiesTruncated;
            } finally {
                if (metrics != null) metrics.metadataPreflightNanos += System.nanoTime() - started;
            }
        }

        private FluidState readFluidState(BlockState state) {
            if (metrics != null) metrics.fluidReads++;
            return state.getFluidState();
        }

        private FluidFacts readFluid(BlockFacts block) {
            long started = metrics == null ? 0 : System.nanoTime();
            try {
                BlockState state = block.state();
                String id = block.id();
                FluidState fluid = readFluidState(state);
                String fluidId = BuiltInRegistries.FLUID.getKey(fluid.getType()).toString();
                boolean source = fluid.isSource();
                int hazards = 0;
                if (fluid.is(FluidTags.LAVA)) hazards |= LAVA;
                if (fluid.is(FluidTags.WATER)) hazards |= WATER;
                if (CONTACT_HAZARDS.contains(id)) hazards |= CONTACT_DAMAGE;
                if ((id.equals("minecraft:campfire") || id.equals("minecraft:soul_campfire"))
                        && state.hasProperty(BlockStateProperties.LIT) && state.getValue(BlockStateProperties.LIT)) hazards |= CONTACT_DAMAGE;
                if (id.equals("minecraft:powder_snow")) hazards |= POWDER_SNOW;
                if (id.equals("minecraft:cobweb")) hazards |= SLOWDOWN;
                return new FluidFacts(fluidId, source, hazards);
            } finally {
                if (metrics != null) metrics.fluidHazardNanos += System.nanoTime() - started;
            }
        }

        private CollisionFacts readCollision(BlockFacts block) {
            long started = metrics == null ? 0 : System.nanoTime();
            BlockPos pos = block.pos();
            ShapeView view = new ShapeView(this, pos);
            try {
                VoxelShape shape = block.state().getCollisionShape(view, pos, collisionContext);
                boolean empty = shape.isEmpty();
                boolean topFull = !empty && Block.isFaceFull(shape, Direction.UP);
                AABB bounds = null;
                if (!empty) {
                    bounds = shape.bounds();
                    if (!Double.isFinite(bounds.minX) || !Double.isFinite(bounds.minY) || !Double.isFinite(bounds.minZ)
                            || !Double.isFinite(bounds.maxX) || !Double.isFinite(bounds.maxY) || !Double.isFinite(bounds.maxZ)) {
                        throw new IllegalStateException("Nonfinite collision bounds");
                    }
                }
                // Publish facts atomically, only after every mod-provided shape operation succeeds.
                return !view.unknown ? new CollisionFacts(true, empty, topFull, bounds, null)
                        : CollisionFacts.unknown("unavailable_shape_context");
            } catch (RuntimeException exception) {
                // A custom block must not make unloaded terrain look like walkable air.
                return CollisionFacts.unknown("block_shape_failed");
            } finally {
                if (metrics != null) metrics.collisionNanos += System.nanoTime() - started;
            }
        }
    }

    private static final int LAVA = 1, WATER = 2, CONTACT_DAMAGE = 4, POWDER_SNOW = 8, SLOWDOWN = 16;
    private record BlockFacts(BlockPos pos, BlockState state, String id, boolean air) { }
    private record FluidFacts(String id, boolean source, int hazards) { }
    private record CollisionFacts(boolean known, boolean empty, boolean topFull, AABB bounds, String unknownReason) {
        static CollisionFacts unknown(String reason) { return new CollisionFacts(false, false, false, null, reason); }
    }

    /** Collision hooks get a bounded, read-only neighborhood and never a live Level. */
    private static final class ShapeView implements BlockGetter {
        private final LoadedSource source;
        private final BlockPos center;
        private int reads;
        private boolean unknown;
        ShapeView(LoadedSource source, BlockPos center) { this.source = source; this.center = center; }
        @Override public BlockState getBlockState(BlockPos pos) {
            if (source.metrics != null) source.metrics.shapeContextReads++;
            if (++reads > 64 || Math.abs((long) pos.getX() - center.getX()) > 1
                    || Math.abs((long) pos.getY() - center.getY()) > 1 || Math.abs((long) pos.getZ() - center.getZ()) > 1
                    || source.availability(pos.getX(), pos.getY(), pos.getZ()) != TerrainScan.Availability.LOADED) {
                unknown = true;
                return Blocks.AIR.defaultBlockState();
            }
            return source.readBlockState(pos);
        }
        @Override public FluidState getFluidState(BlockPos pos) { return source.readFluidState(getBlockState(pos)); }
        @Override public BlockEntity getBlockEntity(BlockPos pos) { unknown = true; return null; }
        @Override public int getHeight() { return source.level.getHeight(); }
        @Override public int getMinBuildHeight() { return source.level.getMinBuildHeight(); }
    }

    private static <T extends Comparable<T>> String propertyName(Property<T> property, Comparable<?> value) {
        @SuppressWarnings("unchecked") T typed = (T) value;
        return property.getName(typed);
    }
    private static String bounded(String value, int length) { return value.length() > length ? value.substring(0, length) : value; }
}
