package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** Small wire contract. Planning and crafting combinations belong to the caller. */
record ClientActionRequest(String id, String action, long timeoutMs, List<Point> waypoints,
        Cell target, Cell support, String face, int hotbarSlot, boolean jump, boolean sneak,
        int containerId, int slot, int button, String clickType, JsonObject original) {
    record Point(double x, double y, double z, boolean jump) { }
    record Cell(int x, int y, int z) { }
    static final Set<String> LEGACY_ACTIONS = Set.of("follow_path", "break_block", "place_block", "click_slot", "recover_environment", "combat_entity", "boat_drive", "boat_mount", "boat_dismount");
    static final Set<String> CAPABILITY_ACTIONS = Set.of("interact_block", "use_item", "select_hotbar", "close_menu", "attack_entity", "shoot_entity", "gateway_pearl", "movement_budget_start", "movement_budget_finish");
    static final Set<String> ACTIONS = java.util.stream.Stream.concat(LEGACY_ACTIONS.stream(), CAPABILITY_ACTIONS.stream()).collect(java.util.stream.Collectors.toUnmodifiableSet());
    static final Set<String> FACES = Set.of("up", "down", "north", "south", "east", "west");
    static final Set<String> CLICKS = Set.of("pickup", "quick_move", "swap", "throw", "pickup_all", "quick_craft");

    static ClientActionRequest parse(JsonObject body) {
        String id = string(body, "action_id");
        require(!id.isBlank() && id.length() <= 128, "invalid_action_id");
        String action = string(body, "action");
        require(ACTIONS.contains(action), "unsupported_action");
        if(body.has("encounter_mode") || body.has("encounter_scope") || body.has(EncounterRequest.PAUSE_ON_TERMINAL))
            require(action.equals("combat_entity"),"encounter_requires_combat_entity");
        if (body.has("sprint")) {
            bool(body, "sprint", false);
            require(action.equals("follow_path"), "sprint_requires_follow_path");
        }
        if (action.equals("follow_path") || action.equals("break_block") || action.equals("place_block"))
            validateNavigationBinding(body);
        boolean recovery = action.equals("recover_environment");
        long timeout = integer(body, "timeout_ms", recovery ? 0 : 15000);
        require((recovery && timeout == 0) || (timeout >= 50 && timeout <= 600000), "invalid_timeout_ms");
        int hotbar = integer(body, "hotbar_slot", -1);
        require(hotbar >= -1 && hotbar <= 8, "invalid_hotbar_slot");
        List<Point> points = new ArrayList<>();
        Cell target = null, support = null;
        String face = null, click = null;
        int container = -1, slot = -1, button = 0;
        if (action.equals("follow_path") || recovery) {
            require(body.has("waypoints") && body.get("waypoints").isJsonArray(), "invalid_waypoints");
            for (JsonElement item : body.getAsJsonArray("waypoints")) {
                require(item.isJsonObject(), "invalid_waypoint");
                JsonObject point = item.getAsJsonObject();
                points.add(new Point(number(point, "x"), number(point, "y"), number(point, "z"), bool(point, "jump", false)));
            }
            require((recovery || !points.isEmpty()) && points.size() <= 512, "invalid_waypoints");
        } else if (action.equals("break_block") || action.equals("interact_block")) {
            target = cell(body, "target");
            if(action.equals("interact_block")){ face=string(body,"face"); require(FACES.contains(face),"invalid_face"); }
        } else if (action.equals("place_block")) {
            support = cell(body, "support");
            face = string(body, "face");
            require(FACES.contains(face), "invalid_face");
        } else if (MovementBudget.budgetAction(action)) {
            // Explicit no-input lifetime operation, with normal action-ID deduplication.
        } else if (action.equals("gateway_pearl")) {
            target=cell(body,"target");CapabilityGateway.validate(body);
        } else if (action.equals("use_item")) {
            require(hotbar>=0,"use_item_hotbar_required");
            int ticks=integer(body,"use_ticks",40);
            require(ticks>=1 && ticks<=100,"invalid_use_ticks");
        } else if (action.equals("select_hotbar")) {
            require(hotbar>=0,"select_hotbar_required");
        } else if (action.equals("close_menu")) {
            require(integer(body,"container_id",-1)>=0,"invalid_container_id");
        } else if (action.equals("attack_entity") || action.equals("shoot_entity")) {
            CapabilityTargetAction.validate(body);
        } else if (action.equals("boat_mount") || action.equals("boat_dismount")) {
            BoatTransferRequest.parse(body);
        } else if (action.equals("boat_drive")) {
            BoatDriveRequest.parse(body);
        } else if (action.equals("combat_entity")) {
            BoundedCombatRequest.parse(body);
        } else {
            container = integer(body, "container_id", -1);
            require(container >= 0, "invalid_container_id");
            require(body.has("slot") && body.has("button"), "missing_slot_or_button");
            slot = integer(body, "slot", -1);
            button = integer(body, "button", -1);
            click = string(body, "click_type");
            require(CLICKS.contains(click), "invalid_click_type");
            // These are vanilla ClickType button encodings, not an inventory policy.
            require(switch (click) {
                case "pickup", "quick_move", "throw", "pickup_all" -> button == 0 || button == 1;
                case "swap" -> (button >= 0 && button <= 8) || button == 40;
                case "quick_craft" -> button >= 0 && button <= 10 && (button & 3) <= 2;
                default -> false;
            }, "invalid_button");
            require(slot >= 0 || slot == -999, "invalid_slot");
        }
        ClientActionRequest request = new ClientActionRequest(id, action, timeout, List.copyOf(points), target, support, face, hotbar,
                bool(body, "jump", false), bool(body, "sneak", false), container, slot, button, click, body.deepCopy());
        CoordinationStepGuard.validate(request);
        CapabilityGuard.validate(request);
        MovementBudget.validate(request);
        return request;
    }

    private static void validateNavigationBinding(JsonObject body) {
        boolean epoch = body.has("expected_navigation_epoch"), origin = body.has("expected_origin");
        require(epoch == origin, "navigation_binding_pair_required");
        if (!epoch) return;
        double n = number(body, "expected_navigation_epoch");
        require(n >= 0 && n <= 9007199254740991L && n == Math.rint(n), "invalid_navigation_epoch");
        require(body.get("expected_origin").isJsonObject(), "invalid_expected_origin");
        JsonObject point = body.getAsJsonObject("expected_origin");
        number(point, "x"); number(point, "y"); number(point, "z");
    }

    static String string(JsonObject body, String key) {
        JsonElement v = body.get(key);
        require(v != null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isString(), "invalid_" + key);
        return v.getAsString();
    }
    static boolean bool(JsonObject body, String key, boolean fallback) {
        if (!body.has(key)) return fallback;
        JsonElement v = body.get(key);
        require(v.isJsonPrimitive() && v.getAsJsonPrimitive().isBoolean(), "invalid_" + key);
        return v.getAsBoolean();
    }
    private static double number(JsonObject body, String key) {
        JsonElement v = body.get(key);
        require(v != null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber(), "invalid_" + key);
        double n = v.getAsDouble();
        require(Double.isFinite(n), "invalid_" + key);
        return n;
    }
    static int integer(JsonObject body, String key, int fallback) {
        if (!body.has(key)) return fallback;
        double n = number(body, key);
        require(n == Math.rint(n) && n >= Integer.MIN_VALUE && n <= Integer.MAX_VALUE, "invalid_" + key);
        return (int) n;
    }
    private static Cell cell(JsonObject body, String key) {
        require(body.has(key) && body.get(key).isJsonObject(), "invalid_" + key);
        JsonObject c = body.getAsJsonObject(key);
        require(c.has("x") && c.has("y") && c.has("z"), "invalid_" + key);
        return new Cell(integer(c, "x", 0), integer(c, "y", 0), integer(c, "z", 0));
    }
    static void require(boolean condition, String message) {
        if (!condition) throw new Rejected(400, message);
    }
    static final class Rejected extends RuntimeException {
        final int httpStatus;
        final JsonObject capabilitySourceFreshness;
        final JsonObject scopedMovementResponseSize;
        final JsonObject routeEntityRejection;
        final JsonObject routeTerrainRejection;
        final JsonObject routeThreatRejection;
        final JsonObject nativeAdmission;
        final JsonObject nativeEntityDiagnostic;
        Rejected(int httpStatus, String reason) { this(httpStatus, reason, null); }
        Rejected(int httpStatus, String reason, JsonObject freshness) {
            this(httpStatus,reason,freshness,null);
        }
        Rejected(int httpStatus,String reason,JsonObject freshness,JsonObject movementSize) {
            this(httpStatus,reason,freshness,movementSize,null);
        }
        Rejected(int httpStatus,String reason,JsonObject freshness,JsonObject movementSize,JsonObject routeEntityRejection) {
            this(httpStatus,reason,freshness,movementSize,routeEntityRejection,null);
        }
        Rejected(int httpStatus,String reason,JsonObject freshness,JsonObject movementSize,JsonObject routeEntityRejection,JsonObject routeTerrainRejection) {
            this(httpStatus,reason,freshness,movementSize,routeEntityRejection,routeTerrainRejection,null);
        }
        Rejected(int httpStatus,String reason,JsonObject freshness,JsonObject movementSize,JsonObject routeEntityRejection,JsonObject routeTerrainRejection,JsonObject routeThreatRejection) {
            this(httpStatus,reason,freshness,movementSize,routeEntityRejection,routeTerrainRejection,routeThreatRejection,null,null);
        }
        private Rejected(int httpStatus,String reason,JsonObject freshness,JsonObject movementSize,JsonObject routeEntityRejection,JsonObject routeTerrainRejection,JsonObject routeThreatRejection,JsonObject nativeAdmission,JsonObject nativeEntityDiagnostic) {
            super(reason); this.httpStatus = httpStatus;
            this.nativeAdmission=nativeAdmission==null?null:nativeAdmission.deepCopy();
            this.nativeEntityDiagnostic=nativeEntityDiagnostic==null?null:nativeEntityDiagnostic.deepCopy();
            this.routeThreatRejection=routeThreatRejection==null?null:routeThreatRejection.deepCopy();
            this.routeTerrainRejection=routeTerrainRejection==null?null:routeTerrainRejection.deepCopy();
            this.routeEntityRejection=routeEntityRejection==null?null:routeEntityRejection.deepCopy();
            capabilitySourceFreshness = freshness == null ? null : freshness.deepCopy();
            scopedMovementResponseSize = httpStatus==409 && reason.equals("scoped_movement_response_evidence_too_large")
                    && movementSize!=null ? movementSize.deepCopy() : null;
        }
        Rejected withNativeAdmission(JsonObject proof) {
            return new Rejected(httpStatus,getMessage(),capabilitySourceFreshness,scopedMovementResponseSize,
                routeEntityRejection,routeTerrainRejection,routeThreatRejection,proof,nativeEntityDiagnostic);
        }
        Rejected withNativeEntityDiagnostic(JsonObject diagnostic) {
            return new Rejected(httpStatus,getMessage(),capabilitySourceFreshness,scopedMovementResponseSize,
                routeEntityRejection,routeTerrainRejection,routeThreatRejection,nativeAdmission,diagnostic);
        }
        JsonObject response() {
            JsonObject body = new JsonObject();
            body.addProperty("ok", false); body.addProperty("error", getMessage());
            if (capabilitySourceFreshness != null)
                body.add("capability_source_freshness", capabilitySourceFreshness.deepCopy());
            if(scopedMovementResponseSize!=null)body.add("scoped_movement_response_size",scopedMovementResponseSize.deepCopy());
            if(routeEntityRejection!=null)body.add("route_entity_rejection",routeEntityRejection.deepCopy());
            if(routeThreatRejection!=null)body.add("route_threat_rejection",routeThreatRejection.deepCopy());
            if(nativeAdmission!=null)body.add("native_admission",nativeAdmission.deepCopy());
            if(nativeEntityDiagnostic!=null)body.add("native_entity_rejection",nativeEntityDiagnostic.deepCopy());
            return body;
        }
    }
}
