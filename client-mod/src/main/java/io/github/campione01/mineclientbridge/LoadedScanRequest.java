package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.LinkedHashSet;
import java.util.Set;

/** Strict bounded request; null Y limits mean the dimension's full legal build height. */
record LoadedScanRequest(String id, String mode, Bounds bounds, Set<String> oreIds, Set<String> biomeIds, boolean explicitBlockFilter, boolean requireWater, int waterRadius, String sort, int maxResults) {
    static final Set<String> DEFAULT_ORES = Set.of("minecraft:coal_ore", "minecraft:deepslate_coal_ore",
            "minecraft:iron_ore", "minecraft:deepslate_iron_ore", "minecraft:copper_ore", "minecraft:deepslate_copper_ore",
            "minecraft:gold_ore", "minecraft:deepslate_gold_ore", "minecraft:redstone_ore", "minecraft:deepslate_redstone_ore",
            "minecraft:lapis_ore", "minecraft:deepslate_lapis_ore", "minecraft:diamond_ore", "minecraft:deepslate_diamond_ore",
            "minecraft:emerald_ore", "minecraft:deepslate_emerald_ore", "minecraft:nether_gold_ore",
            "minecraft:nether_quartz_ore", "minecraft:ancient_debris");
    record Bounds(int minX, int maxX, int minZ, int maxZ, Integer minY, Integer maxY) { }
    boolean ores() { return mode.equals("ores") || mode.equals("blocks") || mode.equals("both") || (surfaceResults() && explicitBlockFilter); }
    boolean biomes() { return mode.equals("biomes"); }
    boolean surfaceResults() { return mode.equals("cherry_sites") || mode.equals("surface_sites") || mode.equals("both"); }
    boolean sites() { return mode.equals("cherry_sites") || mode.equals("surface_sites") || mode.equals("both") || requireWater; }
    static LoadedScanRequest parse(JsonObject body) {
        keys(body, Set.of("id", "mode", "bounds", "ore_ids", "block_ids", "biome_ids", "require_water", "water_radius", "sort", "max_results"));
        String id = id(body);
        String mode = body.has("mode") ? string(body.get("mode")) : "both";
        if (!Set.of("ores", "cherry_sites", "both", "blocks", "biomes", "surface_sites").contains(mode)) throw bad("invalid_scan_mode");
        Bounds bounds = null;
        if (body.has("bounds")) {
            if (!body.get("bounds").isJsonObject()) throw bad("invalid_scan_bounds");
            JsonObject b = body.getAsJsonObject("bounds");
            keys(b, Set.of("min_x", "max_x", "min_z", "max_z", "min_y", "max_y"));
            bounds = new Bounds(integer(b, "min_x", -30_000_000, 30_000_000), integer(b, "max_x", -30_000_000, 30_000_000),
                    integer(b, "min_z", -30_000_000, 30_000_000), integer(b, "max_z", -30_000_000, 30_000_000),
                    b.has("min_y") ? integer(b, "min_y", -1_000_000, 1_000_000) : null,
                    b.has("max_y") ? integer(b, "max_y", -1_000_000, 1_000_000) : null);
            validateXZ(bounds);
            if (bounds.minY != null && bounds.maxY != null && bounds.minY > bounds.maxY) throw bad("invalid_scan_bounds");
        }
        if(body.has("ore_ids")&&body.has("block_ids"))throw bad("duplicate_block_filter");
        String idsKey=body.has("block_ids")?"block_ids":"ore_ids";
        Set<String> ores = body.has(idsKey)?ids(body,idsKey):DEFAULT_ORES;
        Set<String> biomes=body.has("biome_ids")?ids(body,"biome_ids"):
                (mode.equals("cherry_sites")?Set.of("minecraft:cherry_grove"):Set.of());
        if(mode.equals("biomes")&&biomes.isEmpty())throw bad("biome_ids_required");
        if(mode.equals("biomes")&&body.has(idsKey))throw bad("block_filter_requires_blocks_mode");
        boolean water=mode.equals("cherry_sites");
        if(body.has("require_water")){
            JsonElement value=body.get("require_water");
            if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isBoolean())throw bad("invalid_require_water");
            water=value.getAsBoolean();
        }
        int waterRadius=body.has("water_radius")?integer(body,"water_radius",0,128):48;
        String sort=body.has("sort")?string(body.get("sort")):"count";
        if(!Set.of("count","density","distance").contains(sort))throw bad("invalid_scan_sort");
        int limit = body.has("max_results") ? integer(body, "max_results", 1, 256) : 64;
        return new LoadedScanRequest(id, mode, bounds, ores, biomes, body.has(idsKey), water, waterRadius, sort, limit);
    }
    private static Set<String> ids(JsonObject body,String key){
        if(!body.get(key).isJsonArray()||body.getAsJsonArray(key).size()>32||body.getAsJsonArray(key).isEmpty())throw bad("invalid_"+key);
        Set<String> values=new LinkedHashSet<>();
        for(JsonElement value:body.getAsJsonArray(key)){
            String id=string(value);
            if(!id.matches("[a-z0-9_.-]{1,40}:[a-z0-9_./-]{1,100}"))throw bad("invalid_"+key);
            values.add(id);
        }
        return Set.copyOf(values);
    }
    static void validateXZ(Bounds b) {
        long width = (long)b.maxX - b.minX + 1, depth = (long)b.maxZ - b.minZ + 1;
        long chunks = ((long)(b.maxX >> 4) - (b.minX >> 4) + 1) * ((long)(b.maxZ >> 4) - (b.minZ >> 4) + 1);
        if (width < 1 || depth < 1 || width > 2048 || depth > 2048 || chunks > 8192) throw bad("scan_bounds_too_large");
    }
    static String id(JsonObject body) {
        String id = string(body.get("id"));
        if (!id.matches("[A-Za-z0-9_-]{1,64}")) throw bad("invalid_scan_id");
        return id;
    }
    static void keys(JsonObject o, Set<String> allowed) {
        if (!allowed.containsAll(o.keySet())) throw bad("unknown_scan_parameter");
    }
    private static String string(JsonElement value) {
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) throw bad("invalid_scan_parameter");
        return value.getAsString();
    }
    private static int integer(JsonObject object, String name, int min, int max) {
        JsonElement value = object.get(name);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()
                || !value.toString().matches("-?[0-9]{1,8}")) throw bad("invalid_scan_" + name);
        try { int n = value.getAsInt(); if (n < min || n > max) throw bad("invalid_scan_" + name); return n; }
        catch (NumberFormatException bad) { throw bad("invalid_scan_" + name); }
    }
    static ClientActionRequest.Rejected bad(String reason) { return new ClientActionRequest.Rejected(400, reason); }
}
