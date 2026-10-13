package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;

import com.google.gson.JsonObject;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;
import net.minecraft.SharedConstants;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.Bootstrap;
import net.minecraft.util.profiling.InactiveProfiler;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.flag.FeatureFlagSet;
import net.minecraft.world.flag.FeatureFlags;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.DoorBlock;
import net.minecraft.world.level.block.FenceBlock;
import net.minecraft.world.level.block.RotatedPillarBlock;
import net.minecraft.world.level.block.SlabBlock;
import net.minecraft.world.level.block.StairBlock;
import net.minecraft.world.level.block.WallTorchBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.DoorHingeSide;
import net.minecraft.world.level.block.state.properties.DoubleBlockHalf;
import net.minecraft.world.level.block.state.properties.Half;
import net.minecraft.world.level.block.state.properties.SlabType;
import net.minecraft.world.level.block.state.properties.StairsShape;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.level.material.Fluids;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.CollisionContext;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;

/** Actual vanilla state/item algorithms under FML. Not a world or physics test.
 * The synthetic Level is allocation-only: no client/server, chunks, files,
 * connection or game loop is constructed. Block states/items are real registries.
 */
@EnabledIfEnvironmentVariable(named = "MDC_REAL_MOD_LOADER_TESTS", matches = "true")
@Execution(ExecutionMode.SAME_THREAD)
class PlacementVanillaSemanticsTest {
    private static Method predict;

    @BeforeAll static void bootstrap() throws Exception {
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        predict = BlockItem.class.getDeclaredMethod("getPlacementState", BlockPlaceContext.class);
        predict.setAccessible(true);
    }

    /** Never called: Unsafe allocation avoids constructing a real ClientLevel. */
    static final class MemoryLevel extends ClientLevel {
        Map<BlockPos, BlockState> blocks;
        private MemoryLevel() {
            super(null, null, Level.OVERWORLD, null, 0, 0,
                    () -> InactiveProfiler.INSTANCE, null, false, 0L);
            throw new AssertionError("The test must never construct a client world");
        }
        @Override public BlockState getBlockState(BlockPos pos) {
            return blocks.getOrDefault(pos, Blocks.AIR.defaultBlockState());
        }
        @Override public FluidState getFluidState(BlockPos pos) { return Fluids.EMPTY.defaultFluidState(); }
        @Override public boolean hasNeighborSignal(BlockPos pos) { return false; }
        @Override public boolean isUnobstructed(BlockState state, BlockPos pos, CollisionContext context) {
            return true; // Fixture explicitly has no entities; collision/physics is not tested.
        }
        @Override public boolean setBlock(BlockPos pos, BlockState state, int flags) {
            blocks.put(pos.immutable(), state); return true;
        }
        @Override public boolean setBlock(BlockPos pos, BlockState state, int flags, int recursion) {
            return setBlock(pos, state, flags);
        }
        @Override public int getMinBuildHeight() { return -64; }
        @Override public int getHeight() { return 384; }
        @Override public FeatureFlagSet enabledFeatures() { return FeatureFlags.DEFAULT_FLAGS; }
    }

    static MemoryLevel memory() throws Exception {
        Class<?> unsafeType = Class.forName("sun.misc.Unsafe");
        Field field = unsafeType.getDeclaredField("theUnsafe");
        field.setAccessible(true);
        MemoryLevel result = (MemoryLevel) unsafeType.getMethod("allocateInstance", Class.class)
                .invoke(field.get(null), MemoryLevel.class);
        result.blocks = new HashMap<>();
        return result;
    }

    static final class Context extends BlockPlaceContext {
        final Direction facing;
        final Direction[] looking;
        Context(MemoryLevel level, BlockPos support, Direction face, Vec3 hit, Item item,
                Direction facing, Direction... looking) {
            super(level, null, InteractionHand.MAIN_HAND, new ItemStack(item),
                    new BlockHitResult(hit, face, support, false));
            this.facing = facing;
            this.looking = looking.length == 0 ? new Direction[]{Direction.DOWN, facing,
                    Direction.UP, facing.getOpposite(), facing.getClockWise(), facing.getCounterClockWise()} : looking;
        }
        @Override public Direction getHorizontalDirection() { return facing; }
        @Override public Direction getNearestLookingDirection() { return looking[0]; }
        @Override public Direction[] getNearestLookingDirections() { return looking.clone(); }
        @Override public Direction getNearestLookingVerticalDirection() { return Direction.DOWN; }
        @Override public float getRotation() { return facing.toYRot(); }
    }

    static BlockState placement(Context context) throws Exception {
        BlockItem item = (BlockItem) context.getItemInHand().getItem();
        BlockPlaceContext adjusted = item.updatePlacementContext(context);
        assertNotNull(adjusted);
        return (BlockState) predict.invoke(item, adjusted);
    }

    @Test void stairsAndSlabsUseRealFacingHitHalfAndCornerShape() throws Exception {
        MemoryLevel level = memory();
        BlockPos support = new BlockPos(0, 63, 0), target = support.above();
        level.blocks.put(support, Blocks.STONE.defaultBlockState());
        BlockState lower = placement(new Context(level, support, Direction.UP, new Vec3(.5, 64, .5),
                Items.OAK_STAIRS, Direction.NORTH));
        assertNotNull(lower);
        assertEquals(Direction.NORTH, lower.getValue(StairBlock.FACING));
        assertEquals(Half.BOTTOM, lower.getValue(StairBlock.HALF));
        assertEquals(StairsShape.STRAIGHT, lower.getValue(StairBlock.SHAPE));
        Direction[] neighborFacing = {Direction.WEST, Direction.EAST, Direction.WEST, Direction.EAST};
        StairsShape[] shapes = {StairsShape.OUTER_LEFT, StairsShape.OUTER_RIGHT,
                StairsShape.INNER_LEFT, StairsShape.INNER_RIGHT};
        for (int i = 0; i < shapes.length; i++) {
            level.blocks.remove(target.north()); level.blocks.remove(target.south());
            level.blocks.put(i < 2 ? target.north() : target.south(), Blocks.OAK_STAIRS.defaultBlockState()
                    .setValue(StairBlock.FACING, neighborFacing[i]));
            BlockState corner = placement(new Context(level, support, Direction.UP, new Vec3(.5, 64, .5),
                    Items.OAK_STAIRS, Direction.NORTH));
            assertEquals(shapes[i], corner.getValue(StairBlock.SHAPE));
        }
        level.blocks.remove(target.south());
        level.blocks.put(target.north(), Blocks.STONE.defaultBlockState());
        Context upperHit = new Context(level, target.north(), Direction.SOUTH, new Vec3(.5, 64.75, 0),
                Items.OAK_SLAB, Direction.NORTH);
        assertEquals(SlabType.TOP, placement(upperHit).getValue(SlabBlock.TYPE));
        Context lowerHit = new Context(level, target.north(), Direction.SOUTH, new Vec3(.5, 64.25, 0),
                Items.OAK_SLAB, Direction.NORTH);
        assertEquals(SlabType.BOTTOM, placement(lowerHit).getValue(SlabBlock.TYPE));
    }

    @Test void doorHingeAndUpperHalfUseRealTwoCellBehavior() throws Exception {
        MemoryLevel level = memory();
        BlockPos support = new BlockPos(0, 63, 0), target = support.above();
        level.blocks.put(support, Blocks.STONE.defaultBlockState());
        BlockState right = placement(new Context(level, support, Direction.UP, new Vec3(.25, 64, .5),
                Items.OAK_DOOR, Direction.SOUTH));
        BlockState left = placement(new Context(level, support, Direction.UP, new Vec3(.75, 64, .5),
                Items.OAK_DOOR, Direction.SOUTH));
        assertEquals(DoorHingeSide.RIGHT, right.getValue(DoorBlock.HINGE));
        assertEquals(DoorHingeSide.LEFT, left.getValue(DoorBlock.HINGE));
        assertEquals(DoubleBlockHalf.LOWER, left.getValue(DoorBlock.HALF));
        level.blocks.put(target, left);
        Blocks.OAK_DOOR.setPlacedBy(level, target, left, null, new ItemStack(Items.OAK_DOOR));
        assertEquals(left.setValue(DoorBlock.HALF, DoubleBlockHalf.UPPER), level.getBlockState(target.above()));
        BlockState northLeft = left.setValue(DoorBlock.FACING, Direction.NORTH);
        level.blocks.put(target, northLeft);
        level.blocks.put(target.above(), northLeft.setValue(DoorBlock.HALF, DoubleBlockHalf.UPPER));
        level.blocks.put(support.east(), Blocks.STONE.defaultBlockState());
        BlockState paired = placement(new Context(level, support.east(), Direction.UP, new Vec3(1.75,64,.5),
                Items.OAK_DOOR, Direction.NORTH));
        assertEquals(DoorHingeSide.RIGHT, paired.getValue(DoorBlock.HINGE),
                "The adjacent lower door takes precedence over lateral click preference");
        level.blocks.put(target, Blocks.AIR.defaultBlockState());
        level.blocks.put(target.above(), Blocks.STONE.defaultBlockState());
        assertNull(placement(new Context(level, support, Direction.UP, new Vec3(.75,64,.5), Items.OAK_DOOR, Direction.SOUTH)),
                "An occupied upper footprint must block the real placement algorithm");
    }

    @Test void standingAndWallTorchUseSameRealInventoryItem() throws Exception {
        MemoryLevel level = memory();
        BlockPos support = new BlockPos(0, 63, 0), target = support.above();
        level.blocks.put(support, Blocks.STONE.defaultBlockState());
        BlockState standing = placement(new Context(level, support, Direction.UP, new Vec3(.5,64,.5),
                Items.TORCH, Direction.SOUTH, Direction.DOWN, Direction.NORTH, Direction.EAST,
                Direction.SOUTH, Direction.WEST, Direction.UP));
        assertEquals(Blocks.TORCH, standing.getBlock());
        level.blocks.put(target.north(), Blocks.STONE.defaultBlockState());
        BlockState wall = placement(new Context(level, target.north(), Direction.SOUTH, new Vec3(.5,64.5,0),
                Items.TORCH, Direction.NORTH, Direction.NORTH, Direction.DOWN, Direction.EAST,
                Direction.SOUTH, Direction.WEST, Direction.UP));
        assertEquals(Blocks.WALL_TORCH, wall.getBlock());
        assertEquals(Direction.SOUTH, wall.getValue(WallTorchBlock.FACING));
        JsonObject exact = new JsonObject(); exact.addProperty("facing", "south");
        assertTrue(CapabilityPlacement.exact(wall, "minecraft:wall_torch", exact));
        assertFalse(CapabilityPlacement.exact(wall, "minecraft:torch", exact));
        BlockState soul = placement(new Context(level, target.north(), Direction.SOUTH, new Vec3(.5,64.5,0),
                Items.SOUL_TORCH, Direction.NORTH, Direction.NORTH, Direction.DOWN, Direction.EAST,
                Direction.SOUTH, Direction.WEST, Direction.UP));
        assertEquals(Blocks.SOUL_WALL_TORCH, soul.getBlock());
        assertEquals(Direction.SOUTH, soul.getValue(WallTorchBlock.FACING));
    }

    @Test void fenceConnectionsLogAxisAndMixedStairSupportAreEngineDerived() throws Exception {
        MemoryLevel level = memory();
        BlockPos support = new BlockPos(0,63,0), target = support.above();
        level.blocks.put(support, Blocks.STONE.defaultBlockState());
        level.blocks.put(target.east(), Blocks.STONE.defaultBlockState());
        level.blocks.put(target.north(), Blocks.OAK_STAIRS.defaultBlockState().setValue(StairBlock.FACING, Direction.SOUTH));
        BlockState fence = placement(new Context(level,support,Direction.UP,new Vec3(.5,64,.5),Items.OAK_FENCE,Direction.NORTH));
        assertTrue(fence.getValue(FenceBlock.EAST));
        assertTrue(fence.getValue(FenceBlock.NORTH), "The neighbor's full stair back face is a real fence connection");
        for (StairsShape shape : StairsShape.values()) {
            for (Half half : Half.values()) {
                level.blocks.put(target.north(), Blocks.OAK_STAIRS.defaultBlockState()
                        .setValue(StairBlock.FACING, Direction.SOUTH).setValue(StairBlock.SHAPE, shape)
                        .setValue(StairBlock.HALF, half));
                BlockState mixed = placement(new Context(level,support,Direction.UP,new Vec3(.5,64,.5),
                        Items.OAK_FENCE,Direction.NORTH));
                assertEquals(shape != StairsShape.OUTER_LEFT && shape != StairsShape.OUTER_RIGHT,
                        mixed.getValue(FenceBlock.NORTH), "Exact stair side support: " + shape + "/" + half);
            }
        }
        level.blocks.put(target.north(),Blocks.STONE.defaultBlockState());
        BlockState log = placement(new Context(level,target.north(),Direction.SOUTH,new Vec3(.5,64.5,0),Items.OAK_LOG,Direction.NORTH));
        assertEquals(Direction.Axis.Z,log.getValue(RotatedPillarBlock.AXIS));
    }
}
