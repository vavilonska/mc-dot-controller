import com.google.gson.JsonObject;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Reflection oracle used by FiniteAdapterChecks for actual adapter executions.
 * Uses the actual reader methods supplied by their Class objects. No Minecraft
 * behavior or production Cell construction is reimplemented here.
 *
 * Supply a fresh equivalent fixture for EACH path. The legacy class may be
 * a test-only source rename of the pinned mainline TerrainReader (rename its
 * class and constructor only), or loaded through a separate class loader.
 * The actual candidate TerrainReader must be loaded unchanged.
 * Finite Minecraft-signature fixtures are supplied separately by FiniteAdapterChecks.
 */
public final class TerrainReaderDifferentialOracle {
    public interface Fixture extends AutoCloseable {
        Object minecraft();
        /** Ordered callback names, arguments, results/failures; no identity hashes. */
        List<String> trace();
        /** Clear construction/setup calls, leaving only observed adapter work. */
        void clearTrace();
        default void close() { }
    }
    @FunctionalInterface public interface Fixtures {
        Fixture fresh(Class<?> readerClass) throws Exception;
    }
    public record Position(int x, int y, int z) { }
    public record CellView(String availability, String id, boolean collisionKnown,
                           boolean collisionEmpty, boolean fullTopSupport,
                           String fluid, boolean hazardous) { }
    public record Thrown(String type, String message) { }
    public record Observation(JsonObject json, CellView cell, Thrown thrown,
                              List<String> trace, Map<String, Long> metrics) { }
    public record Compared(Observation legacyJson, Observation candidateJson,
                           Observation candidateTyped, Observation candidateTypedMetrics) { }

    private TerrainReaderDifferentialOracle() { }

    /** Actual private LoadedSource.availability/readLoaded and public typed factory. */
    public static Compared compare(String caseName, Class<?> legacyReader,
                                   Class<?> candidateReader, Fixtures fixtures,
                                   Position position) throws Exception {
        Observation legacy = observe(legacyReader, fixtures, position, false, false);
        Observation exported = observe(candidateReader, fixtures, position, false, false);
        Observation typed = observe(candidateReader, fixtures, position, true, false);
        Observation measured = observe(candidateReader, fixtures, position, true, true);
        equal(caseName, "complete JSON object (including missing keys)", legacy.json(), exported.json());
        for (Observation value : List.of(exported, typed, measured)) {
            equal(caseName, "raw failure type/message", legacy.thrown(), value.thrown());
            equal(caseName, "all Cell fields", legacy.cell(), value.cell());
            // JSON paths call availability explicitly; typed paths do so internally.
            // Each starts with an equivalent fresh source, so callback order/counts match.
            equal(caseName, "callback order/counts", legacy.trace(), value.trace());
        }
        for (var entry : measured.metrics().entrySet()) {
            if (entry.getValue() < 0) throw new AssertionError(caseName + ": negative " + entry.getKey());
        }
        return new Compared(legacy, exported, typed, measured);
    }

    public static Observation observe(Class<?> reader, Fixtures factories,
                                      Position p, boolean typed, boolean metricsOn) throws Exception {
        try (Fixture fixture = factories.fresh(reader)) {
            Object mc = fixture.minecraft();
            Object metrics = metricsOn ? construct(nested(reader, "ReadMetrics")) : null;
            fixture.clearTrace();
            JsonObject json = null;
            CellView cell = null;
            Thrown thrown = null;
            try {
                if (typed) {
                    Object source = metricsOn
                            ? call(reader, null, "flatCellSource", mc, metrics)
                            : call(reader, null, "flatCellSource", mc);
                    Object value = call(source.getClass(), source, "read", p.x(), p.y(), p.z());
                    cell = typedView(value);
                } else {
                    Object level = field(mc, "level"), player = field(mc, "player");
                    Class<?> loadedSource = nested(reader, "LoadedSource");
                    Constructor<?> constructor = null;
                    for (var c : loadedSource.getDeclaredConstructors()) {
                        if (c.getParameterCount() == 2) { constructor = c; break; }
                    }
                    if (constructor == null) throw new NoSuchMethodException("LoadedSource(level, context)");
                    constructor.setAccessible(true);
                    Class<?> contextType = constructor.getParameterTypes()[1];
                    Object context = call(contextType, null, "of", player);
                    Object source = constructor.newInstance(level, context);
                    String availability = call(loadedSource, source, "availability", p.x(), p.y(), p.z()).toString();
                    if (availability.equals("LOADED")) {
                        json = (JsonObject) call(loadedSource, source, "readLoaded", p.x(), p.y(), p.z());
                        cell = jsonView(json);
                    } else {
                        cell = new CellView(availability, null, false, false, false, null, false);
                    }
                }
            } catch (InvocationTargetException e) {
                Throwable failure = unwrap(e);
                if (!(failure instanceof RuntimeException)) throw e;
                thrown = new Thrown(failure.getClass().getName(), failure.getMessage());
            }
            return new Observation(json, cell, thrown, List.copyOf(fixture.trace()), metrics(metrics));
        }
    }

    /** JSON is an oracle only for fields the typed Cell promises, not page status. */
    private static CellView jsonView(JsonObject value) {
        return new CellView("LOADED", string(value, "id"), bool(value, "collision_known"),
                bool(value, "collision_empty"), bool(value, "full_top_support"),
                string(value, "fluid"), value.getAsJsonArray("hazards").size() != 0);
    }
    private static CellView typedView(Object value) throws Exception {
        if (value == null) return null;
        Class<?> type = value.getClass();
        Object availability = call(type, value, "availability");
        return new CellView(availability == null ? null : availability.toString(),
                (String) call(type, value, "id"), (Boolean) call(type, value, "collisionKnown"),
                (Boolean) call(type, value, "collisionEmpty"), (Boolean) call(type, value, "fullTopSupport"),
                (String) call(type, value, "fluid"), (Boolean) call(type, value, "hazardous"));
    }
    private static boolean bool(JsonObject obj, String key) {
        return obj.has(key) && !obj.get(key).isJsonNull() && obj.get(key).getAsBoolean();
    }
    private static String string(JsonObject obj, String key) {
        return !obj.has(key) || obj.get(key).isJsonNull() ? null : obj.get(key).getAsString();
    }
    private static Map<String, Long> metrics(Object value) throws Exception {
        Map<String, Long> result = new LinkedHashMap<>();
        if (value != null) for (Field field : value.getClass().getDeclaredFields()) {
            if (field.getType() == long.class && !Modifier.isStatic(field.getModifiers())) {
                field.setAccessible(true); result.put(field.getName(), field.getLong(value));
            }
        }
        return Map.copyOf(result);
    }
    private static Class<?> nested(Class<?> outer, String simpleName) throws Exception {
        for (Class<?> type : outer.getDeclaredClasses()) if (type.getSimpleName().equals(simpleName)) return type;
        throw new ClassNotFoundException(outer.getName() + "$" + simpleName);
    }
    private static Object construct(Class<?> type) throws Exception {
        Constructor<?> constructor = type.getDeclaredConstructor(); constructor.setAccessible(true);
        return constructor.newInstance();
    }
    private static Object field(Object target, String name) throws Exception {
        Field field = target.getClass().getField(name); field.setAccessible(true); return field.get(target);
    }
    private static Object call(Class<?> type, Object target, String name, Object... args) throws Exception {
        Method selected = null;
        for (Method method : type.getDeclaredMethods()) {
            if (!method.getName().equals(name) || method.getParameterCount() != args.length) continue;
            boolean compatible = true;
            for (int i = 0; i < args.length; i++) {
                Class<?> expected = method.getParameterTypes()[i];
                if (args[i] != null && !expected.isInstance(args[i])
                        && !(expected == int.class && args[i] instanceof Integer)) compatible = false;
            }
            if (compatible) { selected = method; break; }
        }
        if (selected == null) throw new NoSuchMethodException(type.getName() + "." + name);
        selected.setAccessible(true); return selected.invoke(target, args);
    }
    private static Throwable unwrap(InvocationTargetException exception) {
        Throwable value = exception;
        while (value instanceof InvocationTargetException wrapped) value = wrapped.getCause();
        return value;
    }
    private static void equal(String name, String what, Object expected, Object actual) {
        if (!Objects.equals(expected, actual))
            throw new AssertionError(name + ": " + what + " expected=" + expected + " actual=" + actual);
    }
}
