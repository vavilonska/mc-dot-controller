package io.github.campione01.mineclientbridge;

import java.util.UUID;
import java.lang.ref.WeakReference;

/** Minecraft-thread-only identity; changes across level replacement and disconnect. */
final class WorldGeneration {
    private static WeakReference<Object> level = new WeakReference<>(null);
    private static String generation;
    private WorldGeneration() { }
    static boolean matches(Object currentLevel,String expected) {
        return currentLevel!=null && level.get()==currentLevel && expected!=null && expected.equals(generation);
    } // Pure read: never allocate or refresh a generation in a final owner fence.
    static String current(Object currentLevel) {
        if (currentLevel == null) { level.clear(); generation = null; return null; }
        if (level.get() != currentLevel) { level = new WeakReference<>(currentLevel); generation = UUID.randomUUID().toString(); }
        return generation;
    }
}
