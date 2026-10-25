package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.Block;

/** One refused dependency cell; metadata only, with no registry/world/shape read. */
final class BlockMenuGeometryDiagnostic {
    private BlockMenuGeometryDiagnostic() { }
    static JsonObject capture(BlockPos pos, Block block) {
        // Callers construct ordinary immutable positions. Do not invoke an
        // unknown coordinate reader just to improve a refusal diagnostic.
        if (pos == null || pos.getClass() != BlockPos.class || block == null) return null;
        Class<?> type = block.getClass();
        String name = type.getName();
        String provider = type.getClassLoader() == Block.class.getClassLoader()
            && name.startsWith("net.minecraft.world.level.block.") && name.length() <= 160
            && name.matches("[A-Za-z0-9_.$]+") ? name : "unclassified_provider";
        JsonObject out = new JsonObject();
        out.addProperty("schema_version", 1);
        out.addProperty("x", pos.getX()); out.addProperty("y", pos.getY()); out.addProperty("z", pos.getZ());
        out.addProperty("provider_class", provider);
        return out;
    }
    static boolean valid(JsonObject value) {
        if (value == null || !value.keySet().equals(Set.of("schema_version", "x", "y", "z", "provider_class"))) return false;
        try {
            if (!value.get("schema_version").isJsonPrimitive() || !value.getAsJsonPrimitive("schema_version").isNumber()
                    || !value.get("schema_version").toString().equals("1")) return false;
            for (String coordinate : new String[]{"x", "y", "z"}) {
                if (!value.get(coordinate).isJsonPrimitive() || !value.getAsJsonPrimitive(coordinate).isNumber()) return false;
                String raw=value.get(coordinate).toString();
                if (!raw.equals(Integer.toString(Integer.parseInt(raw)))) return false;
            }
            if (!value.get("provider_class").isJsonPrimitive() || !value.getAsJsonPrimitive("provider_class").isString()) return false;
            String provider=value.get("provider_class").getAsString();
            return provider.equals("unclassified_provider") || provider.length() <= 160
                && provider.startsWith("net.minecraft.world.level.block.") && provider.matches("[A-Za-z0-9_.$]+");
        } catch (RuntimeException ignored) { return false; }
    }
}
