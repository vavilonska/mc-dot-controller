package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** Finite, single-cell vanilla menu topology. Never a general terrain certificate. */
final class BlockMenuPreflight {
    static final String PROFILE = "block-menu-v1";
    static final Map<String, String> FAMILIES = Map.of(
        "minecraft:crafting_table", "CraftingMenu", "minecraft:furnace", "FurnaceMenu",
        "minecraft:blast_furnace", "BlastFurnaceMenu", "minecraft:smoker", "SmokerMenu",
        "minecraft:dispenser", "DispenserMenu", "minecraft:dropper", "DispenserMenu",
        "minecraft:barrel", "ChestMenu");
    static final int MAX_CELLS = 512;
    private static final Set<String> BODY_HAZARDS = Set.of("minecraft:magma_block", "minecraft:cactus",
        "minecraft:campfire", "minecraft:soul_campfire", "minecraft:fire", "minecraft:soul_fire",
        "minecraft:sweet_berry_bush", "minecraft:powder_snow", "minecraft:wither_rose");
    private BlockMenuPreflight() { }

    static void validateIntent(JsonObject b) {
        require(b.keySet().equals(Set.of("action_id", "action", "target", "face", "timeout_ms",
            "expected_block_id", "expected_block_properties", "expected_open_menu_class", "capability_guard",
            "expected_world_generation", "expected_dimension", "expected_player_uuid", "expected_action_session",
            "expected_hotbar_slot", "expected_held_item")), "block_menu_closed_intent_required");
        String id = ClientActionRequest.string(b, "expected_block_id");
        require(FAMILIES.containsKey(id), "block_menu_unsupported_topology");
        require(("net.minecraft.world.inventory." + FAMILIES.get(id)).equals(
            ClientActionRequest.string(b, "expected_open_menu_class")), "block_menu_family_goal_mismatch");
        require(b.get("expected_block_properties").isJsonObject(), "block_menu_exact_properties_required");
        require(b.get("target").isJsonObject() && b.getAsJsonObject("target").keySet().equals(Set.of("x", "y", "z")),
            "block_menu_exact_target_required");
        target(b); face(b);
    }

    static JsonObject capture(Minecraft mc, JsonObject intent) {
        validateIntent(intent);
        var p = mc.player; var level = mc.level;
        require(p != null && level != null && mc.gameMode != null, "block_menu_missing_context");
        require(mc.screen == null && p.containerMenu == p.inventoryMenu && p.containerMenu.containerId == 0
            && p.containerMenu.getCarried().isEmpty() && !p.isUsingItem(), "block_menu_conflicting_menu_or_use");
        require(p.getMainHandItem().isEmpty() && p.getOffhandItem().isEmpty()
            && p.getInventory().selected == ClientActionRequest.integer(intent, "expected_hotbar_slot", -1),
            "block_menu_empty_unchanged_hands_required");
        Vec3 velocity = p.getDeltaMovement();
        require(p.onGround() && !p.isPassenger() && !p.isFallFlying() && !p.getAbilities().flying && !p.isShiftKeyDown()
            && Double.isFinite(velocity.x) && Double.isFinite(velocity.y) && Double.isFinite(velocity.z)
            && Math.hypot(velocity.x, velocity.z) <= 0.0001 && Math.abs(velocity.y) <= 0.1,
            "block_menu_stationary_grounded_required");
        require(p.hurtTime == 0 && p.getHealth() > 0 && !p.isOnFire() && !p.isInWater()
            && !p.isEyeInFluid(net.minecraft.tags.FluidTags.WATER) && !p.isInLava() && !p.isInPowderSnow,
            "block_menu_physical_hazard");
        BlockPos target = target(intent); Direction face = face(intent);
        require(level.hasChunkAt(target), "block_menu_target_unloaded");
        BlockState state = level.getBlockState(target);
        require(exactVanillaFamily(state, ClientActionRequest.string(intent, "expected_block_id")), "block_menu_unsupported_topology");
        require(properties(state).equals(intent.getAsJsonObject("expected_block_properties")), "block_menu_target_properties_changed");
        var entity = level.getBlockEntity(target);
        String entityClass = entity == null ? "" : entity.getClass().getName();
        String expectedEntity = switch (ClientActionRequest.string(intent, "expected_block_id")) {
            case "minecraft:crafting_table" -> "";
            case "minecraft:furnace" -> "FurnaceBlockEntity";
            case "minecraft:blast_furnace" -> "BlastFurnaceBlockEntity";
            case "minecraft:smoker" -> "SmokerBlockEntity";
            case "minecraft:dispenser" -> "DispenserBlockEntity";
            case "minecraft:dropper" -> "DropperBlockEntity";
            case "minecraft:barrel" -> "BarrelBlockEntity";
            default -> throw new IllegalStateException("unsupported_topology");
        };
        require(entityClass.equals(expectedEntity.isEmpty() ? "" : "net.minecraft.world.level.block.entity." + expectedEntity)
            && (entity == null || !entity.isRemoved() && entity.getBlockPos().equals(target)), "block_menu_block_entity_unconfirmed");
        JsonObject targetCell = cell(mc, target);
        Vec3 eye = p.getEyePosition(), point = faceCenter(target, face);
        double reach = p.blockInteractionRange();
        require(Double.isFinite(reach) && reach > 0 && reach <= 6 && eye.distanceTo(point) <= reach,
            "block_menu_out_of_reach");
        // The complete eye-to-target bounding prism is conservative, finite, and fully loaded.
        // It is specifically a ray dependency footprint, not an arbitrary small-cube completeness claim.
        int x0 = (int)Math.floor(Math.min(eye.x, point.x)), x1 = (int)Math.floor(Math.max(eye.x, point.x));
        int y0 = (int)Math.floor(Math.min(eye.y, point.y)), y1 = (int)Math.floor(Math.max(eye.y, point.y));
        int z0 = (int)Math.floor(Math.min(eye.z, point.z)), z1 = (int)Math.floor(Math.max(eye.z, point.z));
        long count = (long)(x1-x0+1)*(y1-y0+1)*(z1-z0+1);
        require(count > 0 && count <= MAX_CELLS, "block_menu_ray_footprint_over_bound");
        JsonArray corridor = new JsonArray();
        for (int x=x0; x<=x1; x++) for (int y=y0; y<=y1; y++) for (int z=z0; z<=z1; z++)
            corridor.add(cell(mc, new BlockPos(x,y,z)));
        // Initially require the whole standing body above one ordinary full dry support cube.
        AABB body = p.getBoundingBox();
        BlockPos support = BlockPos.containing(p.getX(), body.minY - 0.01, p.getZ());
        require(body.minX >= support.getX() && body.maxX <= support.getX()+1
            && body.minZ >= support.getZ() && body.maxZ <= support.getZ()+1
            && Math.abs(body.minY - (support.getY()+1)) < 0.001, "block_menu_support_topology_unsupported");
        JsonArray bodyCells = new JsonArray();
        for (int y=support.getY(); y<=Math.floor(body.maxY); y++) {
            BlockPos pos = new BlockPos(support.getX(), y, support.getZ());
            JsonObject row = cell(mc, pos); BlockState current = level.getBlockState(pos);
            require(current.getFluidState().isEmpty() && !BODY_HAZARDS.contains(id(current)), "block_menu_support_hazard");
            require(y == support.getY() ? current.isCollisionShapeFullBlock(level, pos)
                : current.getCollisionShape(level, pos).isEmpty(), "block_menu_support_or_body_collision");
            bodyCells.add(row);
        }
        BlockHitResult projected = level.clip(new ClipContext(eye, point.add(point.subtract(eye).normalize().scale(0.00001)),
            ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, p));
        require(hitMatches(projected, target, face, point) && !projected.isInside(), "block_menu_line_of_sight_changed");
        // Shape/clip hooks above may change loaded states or block entity ownership.
        assertRawCells(mc, corridor); assertRawCells(mc, bodyCells);
        require(level.getBlockState(target) == state && level.getBlockEntity(target) == entity
            && (entity == null || !entity.isRemoved()), "block_menu_target_changed_after_geometry_hooks");
        JsonObject out = new JsonObject();
        out.addProperty("version", PROFILE); out.addProperty("topology", "vanilla-single-cell/1");
        out.add("target", targetCell); out.addProperty("block_entity_class", entityClass);
        out.addProperty("expected_open_menu_class", ClientActionRequest.string(intent,"expected_open_menu_class"));
        JsonArray footprint = new JsonArray(); footprint.add(out.get("target").deepCopy()); out.add("menu_footprint", footprint);
        out.add("ray_cells", corridor); out.add("body_cells", bodyCells); out.add("support", pos(support));
        out.add("eye", vector(eye)); out.add("expected_hit", vector(point)); out.addProperty("face", face.getName());
        out.addProperty("reach", reach); out.addProperty("line_of_sight_clear", true);
        out.addProperty("on_ground", true); out.addProperty("stationary", true); out.add("velocity", vector(velocity));
        out.add("body_bounds", bounds(body)); out.addProperty("not_riding_or_flying", true);
        out.addProperty("empty_hands", true); out.addProperty("support_and_body_safe", true);
        assertRawSnapshot(mc, out);
        return out;
    }

    static BlockHitResult actualRay(Minecraft mc, JsonObject intent) {
        mc.gameRenderer.pick(1.0F);
        require(mc.hitResult instanceof BlockHitResult, "block_menu_actual_ray_missing");
        BlockHitResult hit = (BlockHitResult)mc.hitResult;
        requireActualRay(mc, intent, hit);
        return hit;
    }
    static void requireActualRay(Minecraft mc, JsonObject intent, BlockHitResult hit) {
        BlockPos target = target(intent); Direction face = face(intent);
        Vec3 eye = mc.player.getEyePosition(), center = faceCenter(target, face);
        float[] aim = intendedAim(eye, center);
        // Entity's final implementation uses the game's quantized sine table. An ideal
        // double-precision face center is not necessarily a representable view ray.
        Vec3 direction = mc.player.calculateViewVector(aim[1], aim[0]);
        Vec3 expected = representableHit(eye, center, target, face, direction);
        require(expected != null && mc.player.getYRot() == aim[0] && mc.player.getXRot() == aim[1]
            && mc.hitResult == hit && hitMatches(hit, target, face, expected)
            && inCertifiedPrism(eye, center, hit.getLocation()) && !hit.isInside()
            && eye.distanceTo(expected) <= mc.player.blockInteractionRange()
            && eye.distanceTo(hit.getLocation()) <= mc.player.blockInteractionRange(),
            "block_menu_actual_ray_changed");
    }
    static float[] intendedAim(Vec3 eye, Vec3 center) {
        Vec3 d = center.subtract(eye);
        return new float[]{(float)Math.toDegrees(Math.atan2(-d.x, d.z)),
            (float)-Math.toDegrees(Math.atan2(d.y, Math.hypot(d.x, d.z)))};
    }
    static Vec3 representableHit(Vec3 eye, Vec3 center, BlockPos target, Direction face, Vec3 direction) {
        int axis = face.getAxis().ordinal();
        double[] e = {eye.x, eye.y, eye.z}, c = {center.x, center.y, center.z};
        double[] v = {direction.x, direction.y, direction.z};
        double t = (c[axis] - e[axis]) / v[axis];
        if (!Double.isFinite(t) || t <= 0 || v[axis] * (face.getStepX()+face.getStepY()+face.getStepZ()) >= 0) return null;
        double[] h = {e[0] + t*v[0], e[1] + t*v[1], e[2] + t*v[2]};
        h[axis] = c[axis];
        int[] b = {target.getX(), target.getY(), target.getZ()};
        for (int i=0; i<3; i++) if (!Double.isFinite(h[i]) || i != axis && !(h[i] > b[i] && h[i] < b[i]+1)) return null;
        Vec3 hit = new Vec3(h[0], h[1], h[2]);
        // Both endpoints inside this convex prism imply the entire actual segment
        // stays in the cells certified by capture(). Never extend the footprint silently.
        return inCertifiedPrism(eye, center, hit) ? hit : null;
    }
    static boolean inCertifiedPrism(Vec3 eye, Vec3 center, Vec3 point) {
        double[] e={eye.x,eye.y,eye.z}, c={center.x,center.y,center.z}, h={point.x,point.y,point.z};
        for(int i=0;i<3;i++) if(!Double.isFinite(h[i]) || h[i] < Math.floor(Math.min(e[i],c[i]))
            || h[i] >= Math.floor(Math.max(e[i],c[i]))+1) return false;
        return true;
    }
    static JsonObject rayFacts(Minecraft mc, BlockHitResult hit) {
        JsonObject out = new JsonObject(); out.add("target", pos(hit.getBlockPos()));
        out.addProperty("face", hit.getDirection().getName()); out.add("hit", vector(hit.getLocation()));
        out.add("eye", vector(mc.player.getEyePosition())); out.addProperty("reach", mc.player.blockInteractionRange());
        out.addProperty("yaw", (double)mc.player.getYRot()); out.addProperty("pitch", (double)mc.player.getXRot());
        out.addProperty("line_of_sight_clear", true); return out;
    }
    static boolean hitMatches(BlockHitResult hit, BlockPos target, Direction face, Vec3 point) {
        return hit != null && hit.getType() == HitResult.Type.BLOCK && hit.getBlockPos().equals(target)
            && hit.getDirection() == face && hit.getLocation().distanceTo(point) <= 0.0001;
    }
    static boolean exactVanillaFamily(BlockState state, String id) {
        return switch(id) {
            case "minecraft:crafting_table" -> state.getBlock() == Blocks.CRAFTING_TABLE;
            case "minecraft:furnace" -> state.getBlock() == Blocks.FURNACE;
            case "minecraft:blast_furnace" -> state.getBlock() == Blocks.BLAST_FURNACE;
            case "minecraft:smoker" -> state.getBlock() == Blocks.SMOKER;
            case "minecraft:dispenser" -> state.getBlock() == Blocks.DISPENSER;
            case "minecraft:dropper" -> state.getBlock() == Blocks.DROPPER;
            case "minecraft:barrel" -> state.getBlock() == Blocks.BARREL;
            default -> false;
        };
    }
    static JsonObject cell(Minecraft mc, BlockPos pos) {
        require(mc.level.hasChunkAt(pos), "block_menu_dependency_unloaded");
        BlockState state = mc.level.getBlockState(pos);
        var block = state.getBlock();
        if (!staticGeometry(state, block))
            throw new ClientActionRequest.Rejected(409, "block_menu_unknown_geometry_provider")
                .withBlockMenuGeometryRejection(BlockMenuGeometryDiagnostic.capture(pos, block));
        JsonObject out = pos(pos); out.addProperty("id", id(state)); out.add("properties", properties(state));
        out.addProperty("loaded", true); out.addProperty("fluid", BuiltInRegistries.FLUID.getKey(state.getFluidState().getType()).toString());
        JsonArray collision = new JsonArray(), outline = new JsonArray();
        for (AABB box : state.getCollisionShape(mc.level, pos).toAabbs()) { require(collision.size()<32,"block_menu_geometry_over_bound"); collision.add(bounds(box)); }
        for (AABB box : state.getShape(mc.level, pos).toAabbs()) { require(outline.size()<32,"block_menu_geometry_over_bound"); outline.add(bounds(box)); }
        out.add("collision", collision); out.add("outline", outline); return out;
    }
    static boolean staticGeometry(BlockState state) {
        return staticGeometry(state, state.getBlock());
    }
    private static boolean staticGeometry(BlockState state, net.minecraft.world.level.block.Block b) {
        return FAMILIES.keySet().stream().anyMatch(id -> exactVanillaFamily(state,id))
            || b==Blocks.AIR || b==Blocks.CAVE_AIR || b==Blocks.VOID_AIR
            || b==Blocks.STONE || b==Blocks.COBBLESTONE || b==Blocks.DIRT || b==Blocks.GRASS_BLOCK
            || b==Blocks.SMOOTH_STONE || b==Blocks.STONE_BRICKS || b==Blocks.BEDROCK
            || b==Blocks.OAK_PLANKS || b==Blocks.SPRUCE_PLANKS || b==Blocks.BIRCH_PLANKS
            || BlockMenuLogGeometry.allows(b);
    }
    static void assertRawPlayer(Minecraft mc, JsonObject facts) {
        var p=mc.player; JsonObject b=facts.getAsJsonObject("block_menu");
        require(p != null && p.containerMenu == p.inventoryMenu && mc.screen == null && p.containerMenu.getCarried().isEmpty()
            && p.getMainHandItem().isEmpty() && p.getOffhandItem().isEmpty() && !p.isUsingItem()
            && p.getInventory().selected == facts.get("selected_slot").getAsInt()
            && p.getHealth() == facts.get("health").getAsFloat() && p.hurtTime == 0
            && p.onGround() && !p.isPassenger() && !p.isFallFlying() && !p.getAbilities().flying && !p.isShiftKeyDown()
            && !p.isOnFire() && !p.isInWater() && !p.isEyeInFluid(net.minecraft.tags.FluidTags.WATER)
            && !p.isInLava() && !p.isInPowderSnow && vector(p.getEyePosition()).equals(b.get("eye"))
            && vector(p.getDeltaMovement()).equals(b.get("velocity")) && bounds(p.getBoundingBox()).equals(b.get("body_bounds"))
            && p.blockInteractionRange() == b.get("reach").getAsDouble()
            && BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean(), "block_menu_player_changed_after_hooks");
    }
    static void assertRawSnapshot(Minecraft mc, JsonObject snapshot) {
        assertRawCells(mc, snapshot.getAsJsonArray("ray_cells"));
        assertRawCells(mc, snapshot.getAsJsonArray("body_cells"));
        assertRawCells(mc, snapshot.getAsJsonArray("menu_footprint"));
        JsonObject row=snapshot.getAsJsonObject("target");
        var entity=mc.level.getBlockEntity(new BlockPos(row.get("x").getAsInt(),row.get("y").getAsInt(),row.get("z").getAsInt()));
        require((entity==null?"":entity.getClass().getName()).equals(snapshot.get("block_entity_class").getAsString())
            && (entity==null || !entity.isRemoved()),"block_menu_block_entity_changed");
    }
    static void assertRawCells(Minecraft mc, JsonArray cells) {
        for (var element : cells) {
            JsonObject row = element.getAsJsonObject(); BlockPos pos = new BlockPos(row.get("x").getAsInt(), row.get("y").getAsInt(), row.get("z").getAsInt());
            require(mc.level.hasChunkAt(pos), "block_menu_dependency_unloaded_after_hooks");
            BlockState state = mc.level.getBlockState(pos);
            require(id(state).equals(row.get("id").getAsString()) && properties(state).equals(row.get("properties"))
                && BuiltInRegistries.FLUID.getKey(state.getFluidState().getType()).toString().equals(row.get("fluid").getAsString()),
                "block_menu_dependency_changed_after_hooks");
        }
    }
    static JsonObject properties(BlockState state) {
        JsonObject out = new JsonObject();
        for (String key : new TreeSet<>(state.getValues().keySet().stream().map(Property::getName).toList())) {
            Property<?> property = state.getBlock().getStateDefinition().getProperty(key); out.addProperty(key, value(state, property));
        }
        return out;
    }
    private static <T extends Comparable<T>> String value(BlockState s, Property<T> p) { return p.getName(s.getValue(p)); }
    private static String id(BlockState state) { return BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString(); }
    static BlockPos target(JsonObject b) { JsonObject t=b.getAsJsonObject("target"); return new BlockPos(ClientActionRequest.integer(t,"x",0), ClientActionRequest.integer(t,"y",0), ClientActionRequest.integer(t,"z",0)); }
    static Direction face(JsonObject b) { String f=ClientActionRequest.string(b,"face"); require(ClientActionRequest.FACES.contains(f),"invalid_face"); return Direction.valueOf(f.toUpperCase(java.util.Locale.ROOT)); }
    static Vec3 faceCenter(BlockPos p, Direction f) { return Vec3.atCenterOf(p).add(f.getStepX()*.5,f.getStepY()*.5,f.getStepZ()*.5); }
    static JsonObject pos(BlockPos p) { JsonObject o=new JsonObject();o.addProperty("x",p.getX());o.addProperty("y",p.getY());o.addProperty("z",p.getZ());return o; }
    static JsonObject vector(Vec3 p) { JsonObject o=new JsonObject();o.addProperty("x",p.x);o.addProperty("y",p.y);o.addProperty("z",p.z);return o; }
    static JsonArray bounds(AABB b) { JsonArray o=new JsonArray(); for(double v:new double[]{b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ})o.add(v);return o; }
    static void require(boolean condition, String reason) { if(!condition)throw new ClientActionRequest.Rejected(409,reason); }
}
