package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
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
    private static final Set<String> CONTACT_HAZARDS = Set.of("minecraft:fire", "minecraft:soul_fire",
            "minecraft:cactus", "minecraft:magma_block", "minecraft:sweet_berry_bush", "minecraft:wither_rose");

    private TerrainReader() { }

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

        LoadedSource(ClientLevel level, CollisionContext collisionContext) {
            this.level = level;
            this.collisionContext = collisionContext;
        }

        private LevelChunk loadedChunk(int x, int z) {
            long key = ((long) (x >> 4) << 32) | ((z >> 4) & 0xffffffffL);
            if (!chunks.containsKey(key)) {
                // false is essential: missing client chunks stay unknown. No level.getChunk convenience call.
                chunks.put(key, level.getChunkSource().getChunk(x >> 4, z >> 4, ChunkStatus.FULL, false));
            }
            return chunks.get(key);
        }

        @Override public TerrainScan.Availability availability(int x, int y, int z) {
            if (y < level.getMinBuildHeight() || y >= level.getMaxBuildHeight()) return TerrainScan.Availability.OUT_OF_WORLD;
            return loadedChunk(x, z) == null ? TerrainScan.Availability.UNLOADED : TerrainScan.Availability.LOADED;
        }

        @Override public JsonObject readLoaded(int x, int y, int z) {
            BlockPos pos = new BlockPos(x, y, z);
            BlockState state = loadedChunk(x, z).getBlockState(pos);
            JsonObject obj = new JsonObject();
            obj.addProperty("known", true);
            String id = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
            obj.addProperty("id", bounded(id, 160));
            obj.addProperty("id_truncated", id.length() > 160);
            obj.addProperty("air", state.isAir());
            JsonObject properties = new JsonObject();
            int count = 0;
            boolean propertiesTruncated = state.getValues().size() > 8;
            for (Map.Entry<Property<?>, Comparable<?>> property : state.getValues().entrySet()) {
                if (count++ == 8) break;
                String name = property.getKey().getName();
                String value = propertyName(property.getKey(), property.getValue());
                // Keep pathological mod strings from multiplying escaped JSON beyond the response cap.
                if (!name.matches("[a-zA-Z0-9_.:/-]{1,32}") || !value.matches("[a-zA-Z0-9_.:/-]{1,32}")) {
                    propertiesTruncated = true;
                    continue;
                }
                properties.addProperty(name, value);
            }
            obj.add("properties", properties);
            obj.addProperty("properties_truncated", propertiesTruncated);
            FluidState fluid = state.getFluidState();
            String fluidId = BuiltInRegistries.FLUID.getKey(fluid.getType()).toString();
            obj.addProperty("fluid", bounded(fluidId, 160));
            obj.addProperty("fluid_truncated", fluidId.length() > 160);
            obj.addProperty("fluid_source", fluid.isSource());
            JsonArray hazards = new JsonArray();
            if (fluid.is(FluidTags.LAVA)) hazards.add("lava");
            if (fluid.is(FluidTags.WATER)) hazards.add("water");
            if (CONTACT_HAZARDS.contains(id)) hazards.add("contact_damage");
            if ((id.equals("minecraft:campfire") || id.equals("minecraft:soul_campfire"))
                    && state.hasProperty(BlockStateProperties.LIT) && state.getValue(BlockStateProperties.LIT)) hazards.add("contact_damage");
            if (id.equals("minecraft:powder_snow")) hazards.add("powder_snow");
            if (id.equals("minecraft:cobweb")) hazards.add("slowdown");
            obj.add("hazards", hazards);
            obj.addProperty("hazards_exhaustive", false);
            ShapeView view = new ShapeView(this, pos);
            try {
                VoxelShape shape = state.getCollisionShape(view, pos, collisionContext);
                boolean empty = shape.isEmpty();
                boolean topFull = !empty && Block.isFaceFull(shape, Direction.UP);
                JsonArray box = null;
                if (!empty) {
                    AABB bounds = shape.bounds();
                    if (!Double.isFinite(bounds.minX) || !Double.isFinite(bounds.minY) || !Double.isFinite(bounds.minZ)
                            || !Double.isFinite(bounds.maxX) || !Double.isFinite(bounds.maxY) || !Double.isFinite(bounds.maxZ)) {
                        throw new IllegalStateException("Nonfinite collision bounds");
                    }
                    box = new JsonArray();
                    box.add(bounds.minX); box.add(bounds.minY); box.add(bounds.minZ);
                    box.add(bounds.maxX); box.add(bounds.maxY); box.add(bounds.maxZ);
                }
                // Publish facts atomically, only after every mod-provided shape operation succeeds.
                if (!view.unknown) {
                    obj.addProperty("collision_known", true);
                    obj.addProperty("collision_empty", empty);
                    obj.addProperty("full_top_support", topFull);
                    if (box != null) obj.add("collision_bounds", box);
                } else {
                    obj.addProperty("collision_known", false);
                    obj.addProperty("collision_unknown_reason", "unavailable_shape_context");
                }
            } catch (RuntimeException exception) {
                // A custom block must not make unloaded terrain look like walkable air.
                obj.addProperty("collision_known", false);
                obj.addProperty("collision_unknown_reason", "block_shape_failed");
            }
            return obj;
        }
    }

    /** Collision hooks get a bounded, read-only neighborhood and never a live Level. */
    private static final class ShapeView implements BlockGetter {
        private final LoadedSource source;
        private final BlockPos center;
        private int reads;
        private boolean unknown;
        ShapeView(LoadedSource source, BlockPos center) { this.source = source; this.center = center; }
        @Override public BlockState getBlockState(BlockPos pos) {
            if (++reads > 64 || Math.abs((long) pos.getX() - center.getX()) > 1
                    || Math.abs((long) pos.getY() - center.getY()) > 1 || Math.abs((long) pos.getZ() - center.getZ()) > 1
                    || source.availability(pos.getX(), pos.getY(), pos.getZ()) != TerrainScan.Availability.LOADED) {
                unknown = true;
                return Blocks.AIR.defaultBlockState();
            }
            return source.loadedChunk(pos.getX(), pos.getZ()).getBlockState(pos);
        }
        @Override public FluidState getFluidState(BlockPos pos) { return getBlockState(pos).getFluidState(); }
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
