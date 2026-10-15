package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.util.Set;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

/** Real production diagnostics/registry and real engine geometry; never boots a client or world. */
public final class BlockMenuDiagnosticsChecks {
    private static int checks;
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        int sequence = 0;
        for (var stage : BlockMenuDiagnostics.Stage.values()) {
            for (var phase : BlockMenuDiagnostics.Phase.values()) {
                for (boolean release : new boolean[]{false, true}) {
                    var diagnostics = new BlockMenuDiagnostics();
                    diagnostics.mark(stage, phase);
                    var registry = new ActionRegistry();
                    JsonObject intent = JsonParser.parseString("{\"action_id\":\"diagnostic-" + sequence++
                        + "\",\"action\":\"interact_block\",\"target\":{\"x\":2,\"y\":64,\"z\":0},\"face\":\"west\",\"timeout_ms\":1000}").getAsJsonObject();
                    intent.add("capability_guard", JsonParser.parseString("{\"schema_version\":1,\"source_tick\":1,\"source_nano\":\"1\"}"));
                    for (String field : new String[]{"expected_world_generation", "expected_player_uuid", "expected_action_session"})
                        intent.addProperty(field, "offline-test-only");
                    intent.addProperty("expected_dimension", "minecraft:overworld");
                    intent.addProperty("expected_hotbar_slot", 0);
                    intent.add("expected_held_item", new JsonObject());
                    intent.addProperty("expected_block_id", "minecraft:furnace");
                    var request = ClientActionRequest.parse(intent);
                    var entry = registry.begin(request);
                    entry.result.addProperty("dispatched", false);
                    entry.result.addProperty("local_click_hooks_started", true);
                    try { throw new ClientActionRequest.Rejected(409, "block_menu_actual_ray_changed"); }
                    catch (RuntimeException failure) { diagnostics.record(entry, failure, 12345678L); }
                    registry.finishAfterCleanup("failed", "client_action_error", release);
                    JsonObject wire = JsonParser.parseString(BridgeJson.toJson(registry.status(request.id()))).getAsJsonObject();
                    if (sequence <= 2 && args.length == 1)
                        java.nio.file.Files.writeString(java.nio.file.Path.of(args[0], "terminal-cleanup-" + release + ".json"),
                            BridgeJson.toJson(registry.status(request.id())));
                    JsonObject result = wire.getAsJsonObject("result"), evidence = result.getAsJsonObject("block_menu_diagnostics");
                    check(evidence.keySet().equals(Set.of("schema_version", "stage", "phase", "exception_type", "rejection_code", "capture_elapsed_nanos")), "closed diagnostics");
                    check(evidence.get("stage").getAsString().equals(stage.name().toLowerCase(java.util.Locale.ROOT)), "exact stage");
                    check(evidence.get("phase").getAsString().equals(phase.name().toLowerCase(java.util.Locale.ROOT)), "exact phase");
                    check(evidence.get("rejection_code").getAsString().equals("block_menu_actual_ray_changed"), "exact rejection");
                    check(evidence.get("exception_type").getAsString().equals("rejected"), "typed exception");
                    check(evidence.get("capture_elapsed_nanos").getAsString().equals("12345678"), "elapsed is diagnostic only");
                    check(wire.get("reason").getAsString().equals(release ? "client_action_error" : "input_release_unconfirmed"), "terminal semantics retained");
                    check(!result.get("dispatched").getAsBoolean() && result.get("local_click_hooks_started").getAsBoolean(), "effect markers retained");
                    check(!result.has("local_use_started"), "no invented use marker");
                    check(registry.existing(request) == entry && registry.active() == null, "identity retained without replay");
                    diagnostics.phase(BlockMenuDiagnostics.Phase.TERMINAL);
                    check(result.getAsJsonObject("block_menu_diagnostics").equals(entry.result.get("block_menu_diagnostics")), "recorded snapshot independent of later phase");
                    evidence.addProperty("rejection_code", "mutated wire copy");
                    check(entry.result.getAsJsonObject("block_menu_diagnostics").get("rejection_code").getAsString().equals("block_menu_actual_ray_changed"), "wire detached");
                }
            }
        }
        var diagnostics = new BlockMenuDiagnostics();
        for (RuntimeException failure : new RuntimeException[]{new ClientActionRequest.Rejected(409, "password=DO_NOT_SERIALIZE"),
                new ClientActionRequest.Rejected(409, ""), new IllegalArgumentException("password=DO_NOT_SERIALIZE")}) {
            var result = diagnostics.failure(failure, Long.MIN_VALUE);
            check(!result.toString().contains("DO_NOT_SERIALIZE"), "arbitrary messages excluded");
            check(result.get("rejection_code").getAsString().startsWith("unclassified_"), "unknown reason classified");
            check(result.toString().length() < 512, "bounded output");
        }
        for (String code : new String[]{"scoped_capture_budget_exceeded", "scoped_owner_or_context_changed",
                "scoped_profile_facts_changed", "block_menu_raw_inventory_changed", "block_menu_packet_hit_changed"}) {
            check(diagnostics.failure(new ClientActionRequest.Rejected(409, code), 251000000L)
                .get("rejection_code").getAsString().equals(code), "known refusal retained: " + code);
        }
        System.out.println("PASS " + checks + " diagnostics/registry assertions before geometry checks");
        // Synthetic translated geometry, without private trial coordinates or world loading.
        Vec3 eye = new Vec3(0.5, 65.62000000476837, 0.5), point = new Vec3(2.0, 64.5, 0.5);
        BlockPos target = new BlockPos(2, 64, 0);
        check(eye.distanceTo(point) < 4.5, "synthetic finite reach fixture");
        check(BlockMenuPreflight.hitMatches(new BlockHitResult(point, Direction.WEST, target, false), target, Direction.WEST, point), "synthetic exact hit");
        check(!BlockMenuPreflight.hitMatches(new BlockHitResult(point.add(0, .0002, 0), Direction.WEST, target, false), target, Direction.WEST, point), "ray tolerance preserved");
        check(!BlockMenuPreflight.hitMatches(new BlockHitResult(point, Direction.EAST, target, false), target, Direction.WEST, point), "wrong face rejected");
        System.out.println("PASS " + checks + " assertions; genuine production diagnostics/registry/geometry; no client/world bootstrap");
    }
}
