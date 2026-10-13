package io.github.campione01.mineclientbridge;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/** Strict, dependency-free HTTP query validation; no world access occurs here. */
record TerrainQuery(int radius, int vertical, int limit, String cursor, boolean capability, boolean observationClock) {
    TerrainQuery(int radius,int vertical,int limit,String cursor,boolean capability) {this(radius,vertical,limit,cursor,capability,false);}
    static final int DEFAULT_RADIUS = 8;
    static final int MAX_RADIUS = 16;
    static final int DEFAULT_VERTICAL = 4;
    static final int MAX_VERTICAL = 8;
    static final int DEFAULT_LIMIT = 64;
    static final int MAX_LIMIT = 128;
    static final int CAPABILITY_MAX_LIMIT = 1024;
    static final int MAX_BLOCKS = 18_513;

    /** Existing internal callers keep the legacy profile. */
    TerrainQuery(int radius, int vertical, int limit, String cursor) {
        this(radius, vertical, limit, cursor, false);
    }

    static TerrainQuery parse(String raw) {
        Map<String, String> values = new HashMap<>();
        if (raw != null && !raw.isEmpty()) {
            if (raw.length() > 512) throw new IllegalArgumentException("query_too_long");
            for (String part : raw.split("&", -1)) {
                String[] pair = part.split("=", 2);
                if (pair.length != 2) throw new IllegalArgumentException("invalid_query");
                String key = URLDecoder.decode(pair[0], StandardCharsets.UTF_8);
                String value = URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
                if (!Set.of("radius", "vertical", "limit", "cursor", "capability", "observation_clock").contains(key)) {
                    throw new IllegalArgumentException("unknown_parameter");
                }
                if (values.putIfAbsent(key, value) != null) throw new IllegalArgumentException("duplicate_parameter");
            }
        }
        boolean clock=values.containsKey("observation_clock");
        if(clock && !"client-pre-tick-v1".equals(values.get("observation_clock")))throw new IllegalArgumentException("invalid_observation_clock");
        if (values.containsKey("cursor")) {
            String cursor = values.get("cursor");
            if (values.size() != (clock?2:1) || !cursor.matches("[0-9a-f-]{36}:[0-9]{1,5}")) {
                throw new IllegalArgumentException("invalid_cursor");
            }
            return new TerrainQuery(0,0,0,cursor,clock,clock);
        }
        boolean capability = values.containsKey("capability");
        if(clock && !capability)throw new IllegalArgumentException("clock_capability_required");
        if (capability && !values.get("capability").equals("1")) {
            throw new IllegalArgumentException("invalid_capability");
        }
        int radius = integer(values, "radius", DEFAULT_RADIUS, MAX_RADIUS);
        int vertical = integer(values, "vertical", DEFAULT_VERTICAL, MAX_VERTICAL);
        int limit = integer(values, "limit", DEFAULT_LIMIT, capability ? CAPABILITY_MAX_LIMIT : MAX_LIMIT);
        if (limit == 0) throw new IllegalArgumentException("invalid_limit");
        if ((2 * radius + 1) * (2 * radius + 1) * (2 * vertical + 1) > MAX_BLOCKS) {
            throw new IllegalArgumentException("too_many_blocks");
        }
        return new TerrainQuery(radius, vertical, limit, null, capability,clock);
    }

    private static int integer(Map<String, String> values, String key, int fallback, int maximum) {
        if (!values.containsKey(key)) return fallback;
        String raw = values.get(key);
        if (!raw.matches(maximum > 999 ? "[0-9]{1,4}" : "[0-9]{1,3}")) {
            throw new IllegalArgumentException("invalid_" + key);
        }
        int value = Integer.parseInt(raw);
        if (value > maximum) throw new IllegalArgumentException("invalid_" + key);
        return value;
    }
}
