package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Locale;
import java.util.Set;

/** Diagnostic-only finite vocabulary. Never grants authority or changes terminal semantics. */
final class BlockMenuDiagnostics {
    enum Stage { ADMITTED, CLICK, PRE_LOCAL_USE, NATIVE_USE, PACKET_FENCE }
    enum Phase { ADMITTED, AIM, INITIAL_PICK, CLICK_HOOKS, REPEAT_PICK, CAPABILITY_CHECK,
        READINESS, PROFILE, OWNER_BEFORE, FACTS, OWNER_AFTER, RAW_SNAPSHOT, RAW_PLAYER,
        BLOCK_ENTITY, ACTUAL_RAY, RAW_MENU, FINAL_RAY, OWNER_FINAL, NATIVE_USE,
        PACKET_OWNER, PACKET_GUARD, PACKET_HIT, WITNESS, SWING, TERMINAL }
    private Stage stage = Stage.ADMITTED;
    private Phase phase = Phase.ADMITTED;
    private static final Set<String> REJECTIONS = Set.of(
        "block_menu_actual_ray_changed",
        "block_menu_actual_ray_missing",
        "block_menu_block_entity_changed",
        "block_menu_block_entity_replaced",
        "block_menu_block_entity_unconfirmed",
        "block_menu_closed_intent_required",
        "block_menu_conflicting_menu_or_use",
        "block_menu_dependency_changed_after_hooks",
        "block_menu_dependency_unloaded",
        "block_menu_dependency_unloaded_after_hooks",
        "block_menu_empty_unchanged_hands_required",
        "block_menu_exact_inventory_required",
        "block_menu_exact_properties_required",
        "block_menu_exact_target_required",
        "block_menu_family_goal_mismatch",
        "block_menu_geometry_over_bound",
        "block_menu_line_of_sight_changed",
        "block_menu_missing_context",
        "block_menu_nested_use_forbidden",
        "block_menu_out_of_reach",
        "block_menu_packet_guard_changed",
        "block_menu_packet_hit_changed",
        "block_menu_packet_not_dispatched",
        "block_menu_packet_owner_mismatch",
        "block_menu_physical_hazard",
        "block_menu_player_changed_after_hooks",
        "block_menu_post_hook_fence_unavailable",
        "block_menu_profile_required",
        "block_menu_raw_effect_coverage",
        "block_menu_raw_equipment_changed",
        "block_menu_raw_inventory_changed",
        "block_menu_raw_menu_changed",
        "block_menu_raw_player_state_changed",
        "block_menu_ray_footprint_over_bound",
        "block_menu_stationary_grounded_required",
        "block_menu_support_hazard",
        "block_menu_support_or_body_collision",
        "block_menu_support_topology_unsupported",
        "block_menu_target_changed_after_geometry_hooks",
        "block_menu_target_properties_changed",
        "block_menu_target_unloaded",
        "block_menu_unknown_geometry_provider",
        "block_menu_unknown_inventory_container",
        "block_menu_unknown_inventory_slot",
        "block_menu_unsupported_topology",
        "capability_aggressive_enderman",
        "capability_bridge",
        "capability_consumable_changed",
        "capability_context_changed",
        "capability_correct_tool_required",
        "capability_cursor_changed",
        "capability_cursor_not_empty",
        "capability_damage_observed",
        "capability_descent",
        "capability_descent_support_changed",
        "capability_end_entity_budget",
        "capability_environment_hazard",
        "capability_finite_deadline_required",
        "capability_focus_or_pause_changed",
        "capability_guard_required",
        "capability_guard_schema_version",
        "capability_health_guard",
        "capability_held_item_changed",
        "capability_hotbar_binding_required",
        "capability_hotbar_changed",
        "capability_identity_changed",
        "capability_identity_required",
        "capability_input_not_neutral",
        "capability_levitation_stop",
        "capability_menu_changed",
        "capability_menu_revision_required",
        "capability_nearby_effect_cloud",
        "capability_nearby_shulker_bullet",
        "capability_outside_click_not_supported",
        "capability_owner_changed",
        "capability_placement_context_changed",
        "capability_placement_item_mismatch",
        "capability_player_unavailable",
        "capability_private_singleplayer_required",
        "capability_pumpkin_removed",
        "capability_route_binding_required",
        "capability_route_requires_path",
        "capability_screen_opened",
        "capability_slot_changed",
        "capability_source_expired",
        "capability_swap_slot_changed",
        "capability_target_changed",
        "capability_target_unloaded",
        "capability_tool_changed",
        "capability_world_changed",
        "scoped_callback_thread_required",
        "scoped_capture_budget_exceeded",
        "scoped_combat_external_movement_input",
        "scoped_combat_input_identity_changed",
        "scoped_combat_movement_revalidation_failed",
        "scoped_diagnostic_clock_forbidden",
        "scoped_effect_coverage_incomplete",
        "scoped_expected_guard_required",
        "scoped_footprint_incomplete",
        "scoped_integrated_server_missing",
        "scoped_menu_coverage_incomplete",
        "scoped_missing_context",
        "scoped_movement",
        "scoped_movement_admission_only",
        "scoped_movement_budget_evidence_too_large",
        "scoped_movement_external_input",
        "scoped_movement_input_changed_after_hooks",
        "scoped_movement_response_preview_failed",
        "scoped_owner_or_context_changed",
        "scoped_private_singleplayer_required",
        "scoped_profile_facts_changed",
        "scoped_profile_unavailable_for_action");
    void mark(Stage stage, Phase phase) { this.stage = stage; this.phase = phase; }
    void phase(Phase phase) { this.phase = phase; }
    void record(ActionRegistry.Entry entry, RuntimeException failure, long elapsedNanos) {
        entry.result.add("block_menu_diagnostics", failure(failure, elapsedNanos));
    }
    JsonObject failure(RuntimeException failure, long elapsedNanos) {
        JsonObject out = new JsonObject();
        out.addProperty("schema_version", 1);
        out.addProperty("stage", stage.name().toLowerCase(Locale.ROOT));
        out.addProperty("phase", phase.name().toLowerCase(Locale.ROOT));
        boolean rejected = failure instanceof ClientActionRequest.Rejected;
        out.addProperty("exception_type", rejected ? "rejected" : "runtime_exception");
        // Do not serialize arbitrary exception messages, class names, stack traces or user data.
        String code = rejected ? failure.getMessage() : null;
        out.addProperty("rejection_code", code != null && REJECTIONS.contains(code)
            ? code : rejected ? "unclassified_rejection" : "unclassified_runtime_exception");
        out.addProperty("capture_elapsed_nanos", Long.toString(elapsedNanos));
        return out;
    }
}
