package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonElement;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.TreeSet;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.inventory.AbstractContainerMenu;

/** Distinct native-callback admission. No diagnostic clock is accepted as authority. */
final class ScopedNativePreflight {
    static final String VERSION = "scoped-native-preflight/1";
    static final long MAX_NANOS = 250_000_000L;
    static final Set<String> MENU = Set.of("click_slot", "close_menu", "select_hotbar");
    static final Set<String> USE = Set.of("use_item");
    static final Set<String> MENUS = Set.of("InventoryMenu", "ChestMenu", "HopperMenu", "DispenserMenu",
        "ShulkerBoxMenu", "CraftingMenu", "FurnaceMenu", "BlastFurnaceMenu", "SmokerMenu");

    static JsonObject capabilities() {
        JsonObject out = new JsonObject();
        out.addProperty("version", VERSION);
        out.addProperty("private_singleplayer_only", true);
        out.addProperty("same_callback_capture_validate_admit", true);
        out.addProperty("max_acquisition_nanos", Long.toString(MAX_NANOS));
        JsonObject profiles = new JsonObject();
        for (String profile : Set.of("state-menu-v1", "state-use-v1", BlockMenuPreflight.PROFILE, ScopedFlatMovement.PROFILE)) {
            if (profile.equals(BlockMenuPreflight.PROFILE) && !ScopedBlockMenuDispatch.ready()) continue;
            if (profile.equals(ScopedFlatMovement.PROFILE) && !ScopedMovementEntities.ready()) continue;
            JsonArray actions = new JsonArray();
            (profile.equals("state-menu-v1") ? MENU : profile.equals("state-use-v1") ? USE : profile.equals(BlockMenuPreflight.PROFILE) ? Set.of("interact_block") : Set.of("follow_path")).stream().sorted().forEach(actions::add);
            profiles.add(profile, actions);
        }
        if (ScopedMovementEntities.ready()) {
            JsonArray collect=new JsonArray();collect.add("follow_path");profiles.add(ScopedCollectTarget.PROFILE,collect);
            JsonArray descent=new JsonArray();descent.add("follow_path");profiles.add(ScopedStepDownMovement.PROFILE,descent);
        }
        if (ScopedMiningDispatch.ready()) {
            JsonArray mining=new JsonArray();mining.add("break_block");profiles.add(ScopedMining.PROFILE,mining);
        }
        if(ScopedPlacementDispatch.ready()){JsonArray placement=new JsonArray();placement.add("place_block");profiles.add(ScopedPlacement.PROFILE,placement);}
        if(ScopedCombatDispatch.ready()){JsonArray combat=new JsonArray();combat.add("combat_entity");profiles.add(ScopedCombat.PROFILE,combat);}
        out.add("profiles", profiles);
        JsonArray supported = new JsonArray();
        ClientActionRequest.ACTIONS.stream().sorted().forEach(supported::add);
        out.add("guarded_actions", supported);
        out.addProperty("capability_guard_schema_version", 1);
        return out;
    }

    static JsonObject start(JsonObject envelope) {
        Minecraft mc = Minecraft.getInstance();
        require(mc.isSameThread(), "scoped_callback_thread_required");
        require(envelope.keySet().equals(Set.of("preflight", "intent"))
                && envelope.get("preflight").isJsonObject() && envelope.get("intent").isJsonObject(), "invalid_scoped_envelope");
        JsonObject scope = envelope.getAsJsonObject("preflight"), intent = envelope.getAsJsonObject("intent").deepCopy();
        require(scope.keySet().equals(Set.of("version", "profile", "owner_id", "owner_generation", "job_id", "defense_epoch")), "invalid_scoped_profile_request");
        require(VERSION.equals(ClientActionRequest.string(scope, "version")), "unsupported_scoped_version");
        String profile = ClientActionRequest.string(scope, "profile"), action = ClientActionRequest.string(intent, "action");
        require((profile.equals("state-menu-v1") && MENU.contains(action))
                || (profile.equals("state-use-v1") && USE.contains(action))
                || (profile.equals(BlockMenuPreflight.PROFILE) && action.equals("interact_block"))
                || (profile.equals(ScopedStepDownMovement.PROFILE) && action.equals("follow_path") && ScopedMovementEntities.ready())
                || ((profile.equals(ScopedFlatMovement.PROFILE) || profile.equals(ScopedCollectTarget.PROFILE)) && action.equals("follow_path"))
                || (profile.equals(ScopedCombat.PROFILE) && action.equals("combat_entity") && ScopedCombatDispatch.ready())
                || (profile.equals(ScopedMining.PROFILE) && action.equals("break_block") && ScopedMiningDispatch.ready())
                || (profile.equals(ScopedPlacement.PROFILE) && action.equals("place_block") && ScopedPlacementDispatch.ready()), "scoped_profile_unavailable_for_action");
        require(ClientActionRequest.string(scope, "owner_id").matches("[0-9a-f]{32}"), "invalid_scoped_owner");
        require(ClientActionRequest.integer(scope, "owner_generation", -1) > 0, "invalid_scoped_owner_generation");
        require(ClientActionRequest.integer(scope, "defense_epoch", -1) >= 0, "invalid_scoped_defense_epoch");
        require(ClientActionRequest.string(scope, "job_id").matches("[A-Za-z0-9_-]{1,80}"), "invalid_scoped_job");
        require(intent.has("capability_guard") && intent.get("capability_guard").isJsonObject(), "scoped_expected_guard_required");
        require(!intent.has("observation_clock") && !intent.has("observation_clock_profile"), "scoped_diagnostic_clock_forbidden");
        require(mc.player != null && mc.level != null && mc.gameMode != null && CapabilityGuard.privateSingleplayer(mc), "scoped_private_singleplayer_required");
        if(profile.equals(ScopedStepDownMovement.PROFILE))ScopedStepDownMovement.validateIntent(intent);
        if(profile.equals(ScopedCombat.PROFILE))ScopedCombat.validateIntent(intent);
        if(profile.equals(ScopedPlacement.PROFILE))ScopedPlacement.validateIntent(intent);
        if (profile.equals(BlockMenuPreflight.PROFILE)) {
            require(ScopedBlockMenuDispatch.ready(), "block_menu_post_hook_fence_unavailable");
            BlockMenuPreflight.validateIntent(intent);
        }
        Capture capture = new Capture(mc, scope, intent);
        // This guard belongs to facts just captured here, never a re-stamped remote observation.
        intent.add("capability_guard", CapabilityGuard.observation(capture.tick, capture.nano));
        ClientActionRequest parsed = ClientActionRequest.parse(intent);
        capture.commandDigest = digest(parsed.original());
        if(profile.equals(ScopedMining.PROFILE)) {
            capture.mining=new ScopedMining(mc,parsed,capture.nano,capture.tick);
            capture.facts.add("mining",capture.mining.facts());
        }
        if(profile.equals(ScopedPlacement.PROFILE)){capture.placement=new ScopedPlacement(mc,parsed,capture.nano,capture.tick);capture.facts.add("placement",capture.placement.facts());}
        capture.recheck(mc);
        if(capture.movement!=null || capture.mining!=null || capture.placement!=null) {
            capture.requireMovementResponseBudget(parsed);
            capture.recheck(mc); // All preview/state/slot hooks precede the unchanged final admission fences.
        }
        if(capture.stepDown!=null){capture.requireMovementResponseBudget(parsed);capture.recheck(mc);}
        return ClientActions.start(parsed, capture);
    }

    static final class Capture {
        final LocalPlayer player;
        final ClientLevel level;
        final AbstractContainerMenu menu;
        final long tick, nano, ownerRevision;
        final Object integratedServer;
        final String integratedServerIdentity, submittedDigest;
        String commandDigest;
        final JsonObject scope, facts, planningGuard, originalIntent;
        JsonObject finalRay;
        final BlockMenuDiagnostics blockMenuDiagnostics;
        final Object blockMenuEntity;
        final BlockMenuRawState blockMenuRawState;
        final ScopedFlatMovement movement;
        final ScopedStepDownMovement stepDown;
        ScopedMining mining;
        ScopedPlacement placement;
        final ScopedCombat combat;

        Capture(Minecraft mc, JsonObject scope, JsonObject intent) {
            player = mc.player; level = mc.level; menu = player.containerMenu;
            tick = level.getGameTime(); nano = System.nanoTime(); ownerRevision = ClientActions.ownershipRevision();
            integratedServer = mc.getSingleplayerServer();
            integratedServerIdentity = IntegratedServerIdentity.current(integratedServer, CapabilityGuard.privateSingleplayer(mc));
            require(integratedServer != null && integratedServerIdentity != null, "scoped_integrated_server_missing");
            this.scope = scope.deepCopy(); this.planningGuard = intent.getAsJsonObject("capability_guard").deepCopy();
            blockMenuDiagnostics = blockMenu() ? new BlockMenuDiagnostics() : null;
            originalIntent = intent.deepCopy();
            submittedDigest = digest(intent);
            String profile=ClientActionRequest.string(scope,"profile");
            movement = (ScopedFlatMovement.PROFILE.equals(profile) || ScopedCollectTarget.PROFILE.equals(profile))
                ? new ScopedFlatMovement(mc, ClientActionRequest.parse(intent), nano, tick,ScopedCollectTarget.PROFILE.equals(profile)) : null;
            stepDown=ScopedStepDownMovement.PROFILE.equals(profile)?new ScopedStepDownMovement(mc,ClientActionRequest.parse(intent),nano,tick):null;
            combat=ScopedCombat.PROFILE.equals(ClientActionRequest.string(scope,"profile"))
                ? new ScopedCombat(mc,ClientActionRequest.parse(intent),nano) : null;
            facts = captureFacts(mc);
            blockMenuEntity = blockMenu() ? mc.level.getBlockEntity(BlockMenuPreflight.target(originalIntent)) : null;
            blockMenuRawState = blockMenu() ? new BlockMenuRawState(mc, facts) : null;
            recheck(mc);
        }

        boolean blockMenu() { return scope.get("profile").getAsString().equals(BlockMenuPreflight.PROFILE); }

        private JsonObject captureFacts(Minecraft mc) {
            // Geometry hooks first, then slot hooks, then native state snapshots.
            JsonObject block = blockMenu() ? BlockMenuPreflight.capture(mc, originalIntent) : null;
            JsonObject out = facts(mc);
            if (block != null) out.add("block_menu", block);
            if(combat!=null)out.add("combat",combat.facts());
            if (movement != null) out.add("movement", movement.facts());
            if (stepDown != null) out.add("step_down", stepDown.facts());
            if (mining != null) out.add("mining", mining.facts());
            if (placement != null) out.add("placement",placement.facts());
            return out;
        }

        void recheck(Minecraft mc) { recheck(mc, null); }

        private void fence(Minecraft mc, String actionId) {
            boolean owner = actionId == null
                ? ClientActions.ownershipRevision() == ownerRevision && !ClientActions.ownsInput()
                : ClientActions.scopedOwns(actionId, ownerRevision + 1);
            require(mc.isSameThread() && mc.player == player && mc.level == level
                    && mc.player.containerMenu == menu && owner && mc.getSingleplayerServer() == integratedServer
                    && integratedServerIdentity.equals(IntegratedServerIdentity.current(mc.getSingleplayerServer(), CapabilityGuard.privateSingleplayer(mc))),
                    "scoped_owner_or_context_changed");
            long elapsed = System.nanoTime() - nano;
            long maximum = blockMenu() ? Math.min(MAX_NANOS,
                ClientActionRequest.integer(originalIntent, "timeout_ms", 0) * 1_000_000L) : MAX_NANOS;
            require(elapsed >= 0 && elapsed <= maximum && mc.level.getGameTime() == tick, "scoped_capture_budget_exceeded");
        }

        private void recheck(Minecraft mc, String actionId) {
            if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.OWNER_BEFORE);
            fence(mc, actionId);
            // Movement geometry/attribute hooks precede the final generic inventory/menu facts.
            if (movement != null) {
                require(actionId == null, "scoped_movement_admission_only");
                movement.admissionRecheck(mc);
            }
            if(stepDown!=null){require(actionId==null,"step_down_admission_only");stepDown.admissionRecheck(mc);}
            if(combat!=null)combat.admission(mc);
            if(mining!=null)mining.admissionBeforeFacts(mc);
            if(placement!=null)placement.admission(mc);
            if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.FACTS);
            require(facts.equals(captureFacts(mc)), "scoped_profile_facts_changed");
            if(mining!=null)mining.admissionAfterFacts(mc);
            if(placement!=null)placement.admission(mc);
            if(combat!=null)combat.admission(mc);
            // After generic permission hooks, only raw corridor/entity/pose/owner reads remain.
            if (movement != null) movement.admissionRawFence(mc);
            if (stepDown != null) stepDown.admissionRawFence(mc);
            // Fact/slot/shape hooks are not assumed pure. Fence the original owner after them.
            if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.OWNER_AFTER);
            fence(mc, actionId);
            if (blockMenu()) {
                if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.RAW_SNAPSHOT);
                BlockMenuPreflight.assertRawSnapshot(mc, facts.getAsJsonObject("block_menu"));
                if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.RAW_PLAYER);
                BlockMenuPreflight.assertRawPlayer(mc, facts);
                if (actionId != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.BLOCK_ENTITY);
                require(mc.level.getBlockEntity(BlockMenuPreflight.target(originalIntent)) == blockMenuEntity,
                    "block_menu_block_entity_replaced");
            }
        }

        net.minecraft.world.phys.BlockHitResult beforeLocalBlockUse(Minecraft mc, String actionId) {
            if (blockMenuDiagnostics != null) blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.PROFILE);
            require(blockMenu(), "block_menu_profile_required");
            recheck(mc, actionId); // All slot-permission and shape callbacks precede the final pick.
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.ACTUAL_RAY);
            var hit = BlockMenuPreflight.actualRay(mc, originalIntent);
            // No overridable Slot or shape callbacks may run after this pick. Vanilla
            // container data and copied stacks are checked directly, without resampling permissions.
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.RAW_MENU);
            blockMenuRawState.check(mc, facts);
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.RAW_SNAPSHOT);
            BlockMenuPreflight.assertRawSnapshot(mc, facts.getAsJsonObject("block_menu"));
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.RAW_PLAYER);
            BlockMenuPreflight.assertRawPlayer(mc, facts);
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.BLOCK_ENTITY);
            require(mc.level.getBlockEntity(BlockMenuPreflight.target(originalIntent)) == blockMenuEntity,
                "block_menu_block_entity_replaced");
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.FINAL_RAY);
            BlockMenuPreflight.requireActualRay(mc, originalIntent, hit);
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.OWNER_FINAL);
            fence(mc, actionId);
            return hit;
        }

        net.minecraft.world.phys.BlockHitResult beforeBlockMenuEffect(Minecraft mc, String actionId) {
            var hit = beforeLocalBlockUse(mc, actionId);
            blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.WITNESS);
            finalRay = BlockMenuPreflight.rayFacts(mc, hit);
            return hit;
        }

        private void requireMovementResponseBudget(ClientActionRequest request) {
            // Construct a detached production Entry, never insert it into ACTIONS or acquire input ownership.
            ActionRegistry.Entry preview=new ActionRegistry.Entry(request);
            preview.result.add("scoped_native_preflight",witness(request.id()));
            preview.result.addProperty("world_generation",WorldGeneration.current(level));
            JsonObject action=preview.json(true);
            action.addProperty("action_session",ClientActions.session());
            JsonObject budget=MovementBudget.snapshot();
            try {
                // Existing ledger shape is fixed; reserve an additional 8KiB per action for terminal fields/growth.
                require(BridgeJson.toJson(budget).getBytes(StandardCharsets.UTF_8).length<=4096,
                        "scoped_movement_budget_evidence_too_large");
            } catch(java.io.IOException unavailable){throw new ClientActionRequest.Rejected(409,"scoped_movement_response_preview_failed");}
            action.add("movement_budget",budget);
            BridgeServer.requireScopedMovementResponseBudget(action);
        }

        JsonObject witness(String actionId) {
            JsonObject out = serializeWitness(scope,actionId,ClientActions.session(),ownerRevision,
                    integratedServerIdentity,submittedDigest,commandDigest,tick,nano,System.nanoTime(),facts,planningGuard);
            if (blockMenu()) {
                out.addProperty("dispatch_fence_confirmed", finalRay != null);
                if (finalRay != null) out.add("final_ray", finalRay.deepCopy());
                out.addProperty("effect_callback", "native-post-use-hooks-packet/1");
            }
            return out;
        }
    }

    /** Pure production witness emitter, shared with finite wire fixtures. No capture or execution authority. */
    static JsonObject serializeWitness(JsonObject scope,String actionId,String actionSession,long ownerRevision,
            String integratedServerIdentity,String submittedDigest,String commandDigest,long tick,long nano,
            long admittedNano,JsonObject facts,JsonObject planningGuard) {
        JsonObject out = scope.deepCopy();
        out.addProperty("schema_version", 1);
        out.addProperty("action_id", actionId);
        out.addProperty("action_session", actionSession);
        out.addProperty("native_owner_revision", ownerRevision);
        out.addProperty("integrated_server_instance", integratedServerIdentity);
        out.addProperty("submitted_intent_sha256", submittedDigest);
        out.addProperty("command_sha256", commandDigest);
        out.addProperty("command_digest_format", "sorted-json-utf8/1");
        out.addProperty("source_tick", tick);
        out.addProperty("source_nano", Long.toString(nano));
        out.addProperty("admitted_nano", Long.toString(admittedNano));
        out.addProperty("clock_domain", "native-system-nanotime");
        out.addProperty("coverage_complete", true);
        out.addProperty("admitted", true);
        out.add("context", facts.getAsJsonObject("context").deepCopy());
        out.add("facts", facts.deepCopy());
        out.add("planning_guard", planningGuard.deepCopy());
        return out;
    }

    /** Native vanilla data fence. Does not invoke Slot permissions/getItem/isActive or any shape query. */
    private static final class BlockMenuRawState {
        final net.minecraft.world.entity.player.Inventory inventory;
        final AbstractContainerMenu menu;
        final java.util.List<net.minecraft.world.inventory.Slot> slots;
        final net.minecraft.world.Container[] containers;
        final int[] indices;
        final net.minecraft.world.item.ItemStack[] items;
        final java.util.Map<EquipmentSlot, net.minecraft.world.item.ItemStack> equipment = new java.util.EnumMap<>(EquipmentSlot.class);
        final net.minecraft.world.item.ItemStack carried;
        final int revision;
        BlockMenuRawState(Minecraft mc, JsonObject facts) {
            inventory=mc.player.getInventory(); menu=mc.player.containerMenu;
            require(inventory.getClass()==net.minecraft.world.entity.player.Inventory.class
                && menu.getClass()==net.minecraft.world.inventory.InventoryMenu.class, "block_menu_exact_inventory_required");
            slots=java.util.List.copyOf(menu.slots); containers=new net.minecraft.world.Container[slots.size()];
            indices=new int[slots.size()]; items=new net.minecraft.world.item.ItemStack[slots.size()];
            for(int i=0;i<slots.size();i++) {
                var slot=slots.get(i); var container=slot.container;
                require(container.getClass()==net.minecraft.world.entity.player.Inventory.class
                    || container.getClass()==net.minecraft.world.inventory.TransientCraftingContainer.class
                    || container.getClass()==net.minecraft.world.inventory.ResultContainer.class,
                    "block_menu_unknown_inventory_container");
                require(slot.index==i && slot.getClass().getName().startsWith("net.minecraft.world.inventory."),
                    "block_menu_unknown_inventory_slot");
                containers[i]=container; indices[i]=slot.getContainerSlot(); items[i]=container.getItem(indices[i]).copy();
            }
            for(EquipmentSlot slot:EquipmentSlot.values())equipment.put(slot,mc.player.getItemBySlot(slot).copy());
            carried=menu.getCarried().copy();revision=menu.getStateId();
            check(mc,facts);
        }
        void check(Minecraft mc, JsonObject facts) {
            var p=mc.player;
            require(p!=null && p.getInventory()==inventory && p.containerMenu==menu
                && menu.getStateId()==revision && menu.containerId==0 && menu.slots.size()==slots.size()
                && net.minecraft.world.item.ItemStack.matches(carried,menu.getCarried()), "block_menu_raw_menu_changed");
            for(int i=0;i<slots.size();i++) {
                var slot=menu.slots.get(i);
                require(slot==slots.get(i) && slot.index==i && slot.container==containers[i]
                    && net.minecraft.world.item.ItemStack.matches(items[i],containers[i].getItem(indices[i])),
                    "block_menu_raw_inventory_changed");
            }
            for(EquipmentSlot slot:EquipmentSlot.values())require(
                net.minecraft.world.item.ItemStack.matches(equipment.get(slot),p.getItemBySlot(slot)),
                "block_menu_raw_equipment_changed");
            JsonArray effects=new JsonArray();
            for(var effect:p.getActiveEffects()) {
                require(effects.size()<64,"block_menu_raw_effect_coverage");
                JsonObject row=new JsonObject();
                row.addProperty("id",BuiltInRegistries.MOB_EFFECT.getKey(effect.getEffect().value()).toString());
                row.addProperty("amplifier",effect.getAmplifier());row.addProperty("duration",effect.getDuration());effects.add(row);
            }
            require(effects.equals(facts.get("effects")) && p.getFoodData().getFoodLevel()==facts.get("food_level").getAsInt()
                && p.getFoodData().getSaturationLevel()==facts.get("food_saturation").getAsFloat()
                && mc.isWindowActive() && !mc.isPaused() && p.isAlive() && !p.isSpectator(),
                "block_menu_raw_player_state_changed");
        }
    }

    private static JsonObject facts(Minecraft mc) {
        require(mc.player != null && mc.level != null && mc.gameMode != null, "scoped_missing_context");
        LocalPlayer p = mc.player;
        require(p.getInventory().getContainerSize() == 41 && p.containerMenu.slots.size() > 0
                && p.containerMenu.slots.size() <= 256
                && p.containerMenu.getClass().getName().startsWith("net.minecraft.world.inventory.")
                && MENUS.contains(p.containerMenu.getClass().getSimpleName()), "scoped_footprint_incomplete");
        JsonArray permissions = new JsonArray();
        for (var slot : p.containerMenu.slots) {
            JsonObject row = new JsonObject(); row.addProperty("may_pickup", slot.mayPickup(p));
            row.addProperty("may_place_carried", slot.mayPlace(p.containerMenu.getCarried()));
            row.addProperty("max_stack_size", slot.getMaxStackSize()); permissions.add(row);
        }
        JsonObject out = new JsonObject(), context = new JsonObject();
        context.addProperty("world_generation", WorldGeneration.current(mc.level));
        context.addProperty("dimension", mc.level.dimension().location().toString());
        context.addProperty("player_uuid", p.getUUID().toString());
        context.addProperty("action_session", ClientActions.session());
        context.addProperty("integrated_server_instance", IntegratedServerIdentity.current(mc.getSingleplayerServer(), CapabilityGuard.privateSingleplayer(mc)));
        out.add("context", context);
        out.addProperty("private_singleplayer", CapabilityGuard.privateSingleplayer(mc));
        out.addProperty("focused", mc.isWindowActive()); out.addProperty("paused", mc.isPaused());
        out.addProperty("alive", p.isAlive()); out.addProperty("spectator", p.isSpectator());
        out.addProperty("health", p.getHealth()); out.addProperty("hurt_time", p.hurtTime);
        out.addProperty("x", p.getX()); out.addProperty("y", p.getY()); out.addProperty("z", p.getZ());
        out.addProperty("selected_slot", p.getInventory().selected);
        out.addProperty("screen_class", mc.screen == null ? "" : mc.screen.getClass().getName());
        out.addProperty("on_fire", p.isOnFire()); out.addProperty("in_water", p.isInWater());
        out.addProperty("in_lava", p.isInLava()); out.addProperty("powder_snow", p.isInPowderSnow);
        out.addProperty("using_item", p.isUsingItem());
        out.addProperty("food_level", p.getFoodData().getFoodLevel());
        out.addProperty("food_saturation", p.getFoodData().getSaturationLevel());
        out.add("held_inputs", BridgeServer.heldInputsSnapshot(mc));
        JsonArray inventory = new JsonArray();
        for (int i = 0; i < p.getInventory().getContainerSize(); i++) {
            JsonObject row = new JsonObject(); row.addProperty("slot", i);
            row.add("item", BridgeServer.capabilityItemSnapshot(p.getInventory().getItem(i))); inventory.add(row);
        }
        out.add("inventory", inventory);
        out.addProperty("inventory_total", p.getInventory().getContainerSize());
        JsonObject equipment = new JsonObject();
        for (EquipmentSlot slot : EquipmentSlot.values()) equipment.add(slot.getName(), BridgeServer.capabilityItemSnapshot(p.getItemBySlot(slot)));
        out.add("equipment", equipment);
        JsonArray effects = new JsonArray();
        for (var effect : p.getActiveEffects()) {
            require(effects.size() < 64, "scoped_effect_coverage_incomplete");
            JsonObject e = new JsonObject();
            e.addProperty("id", BuiltInRegistries.MOB_EFFECT.getKey(effect.getEffect().value()).toString());
            e.addProperty("amplifier", effect.getAmplifier()); e.addProperty("duration", effect.getDuration()); effects.add(e);
        }
        out.add("effects", effects);
        JsonObject menu = BridgeServer.menuSnapshot(p.containerMenu);
        require(!menu.get("slots_truncated").getAsBoolean(), "scoped_menu_coverage_incomplete");
        menu.add("slot_permissions", permissions); out.add("menu", menu);
        return out;
    }

    /** Canonicalize the actual parsed command, not an unchecked caller hash. */
    static String digest(JsonElement value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(canonical(value).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    private static String canonical(JsonElement value) {
        if (value.isJsonObject()) {
            StringBuilder b = new StringBuilder("{"); boolean first = true;
            for (String key : new TreeSet<>(value.getAsJsonObject().keySet())) {
                if (!first) b.append(','); first = false;
                b.append(quoted(key)).append(':').append(canonical(value.getAsJsonObject().get(key)));
            }
            return b.append('}').toString();
        }
        if (value.isJsonArray()) {
            StringBuilder b = new StringBuilder("["); boolean first = true;
            for (JsonElement child : value.getAsJsonArray()) {
                if (!first) b.append(','); first = false; b.append(canonical(child));
            }
            return b.append(']').toString();
        }
        if (value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()) return quoted(value.getAsString());
        return value.toString();
    }
    private static String quoted(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '\"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> { if (c < 32) out.append(String.format("\\u%04x", (int)c)); else out.append(c); }
            }
        }
        return out.append('\"').toString();
    }

    private static void require(boolean condition, String reason) {
        if (!condition) throw new ClientActionRequest.Rejected(409, reason);
    }
    private ScopedNativePreflight() { }
}
