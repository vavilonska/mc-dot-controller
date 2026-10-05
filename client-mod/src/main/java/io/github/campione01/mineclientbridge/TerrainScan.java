package io.github.campione01.mineclientbridge;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.function.LongSupplier;

/** One bounded scan, used only on the Minecraft thread. No game or networking dependencies. */
final class TerrainScan<T> {
    static final long PAGE_BUDGET_NANOS = 2_000_000L;
    static final long MIN_PAGE_INTERVAL_NANOS = 50_000_000L;
    static final long MAX_AGE_NANOS = 30_000_000_000L;

    enum Availability { LOADED, UNLOADED, OUT_OF_WORLD, READ_FAILED }
    interface Source<T> {
        Availability availability(int x, int y, int z);
        T readLoaded(int x, int y, int z);
    }
    record Cell<T>(int x, int y, int z, Availability availability, T data) { }
    record Page<T>(String generation, int originX, int originY, int originZ,
            int radius, int vertical, int offset, int nextOffset, int total,
            List<Cell<T>> cells, String nextCursor, boolean budgetExhausted, long elapsedNanos) { }
    static final class Failure extends RuntimeException {
        final int status;
        Failure(int status, String code) { super(code); this.status = status; }
    }

    private final LongSupplier clock;
    private WeakReference<Object> world = new WeakReference<>(null);
    private String generation;
    private int originX, originY, originZ, radius, vertical, limit, offset, total;
    private long createdAt, lastRead;
    private boolean hasRead;
    private Page<T> previous;
    private String previousCursor;

    TerrainScan(LongSupplier clock) { this.clock = clock; }

    void clear() {
        world.clear();
        generation = null;
        previous = null;
        previousCursor = null;
        // Keep the rate limit across new scans, disconnects and invalidation.
    }

    Page<T> page(TerrainQuery query, Object currentWorld, int x, int y, int z, Source<T> source) {
        long now = clock.getAsLong();
        if (currentWorld == null) { clear(); throw new Failure(409, "not_in_world"); }
        if (generation != null && world.get() != currentWorld) clear();
        if (generation != null && now - createdAt >= MAX_AGE_NANOS) clear();
        if (query.cursor() != null) {
            if (generation == null) throw new Failure(409, "stale_terrain_cursor");
            if (query.cursor().equals(previousCursor)) return previous; // Safe retry, no world reads.
            if (!query.cursor().equals(generation + ":" + offset) || offset >= total) {
                throw new Failure(409, "stale_terrain_cursor");
            }
        }
        if (hasRead && now - lastRead < MIN_PAGE_INTERVAL_NANOS) throw new Failure(429, "terrain_rate_limited");
        if (query.cursor() == null) {
            // Queries are centered on the current player only; no arbitrary remote coordinates.
            world = new WeakReference<>(currentWorld);
            generation = UUID.randomUUID().toString();
            originX = x; originY = y; originZ = z;
            radius = query.radius(); vertical = query.vertical(); limit = query.limit();
            total = (2 * radius + 1) * (2 * radius + 1) * (2 * vertical + 1);
            offset = 0; createdAt = now;
            previous = null; previousCursor = null;
        }
        hasRead = true;
        lastRead = now;
        int start = offset;
        int width = 2 * radius + 1;
        List<Cell<T>> cells = new ArrayList<>(limit);
        boolean budgetExhausted = false;
        while (offset < total && cells.size() < limit) {
            // Cooperative wall-time budget; one modded block callback cannot be preempted safely.
            if (!cells.isEmpty() && clock.getAsLong() - now >= PAGE_BUDGET_NANOS) {
                budgetExhausted = true;
                break;
            }
            int cx = originX - radius + offset % width;
            int cz = originZ - radius + (offset / width) % width;
            int cy = originY - vertical + offset / (width * width);
            Availability availability;
            T data;
            try {
                availability = source.availability(cx, cy, cz);
                data = availability == Availability.LOADED ? source.readLoaded(cx, cy, cz) : null;
            } catch (RuntimeException exception) {
                availability = Availability.READ_FAILED;
                data = null;
            }
            cells.add(new Cell<>(cx, cy, cz, availability, data));
            offset++;
        }
        long elapsed = clock.getAsLong() - now;
        if (elapsed >= PAGE_BUDGET_NANOS && offset < total) budgetExhausted = true;
        Page<T> result = new Page<>(generation, originX, originY, originZ, radius, vertical,
                start, offset, total, List.copyOf(cells), offset < total ? generation + ":" + offset : null,
                budgetExhausted, elapsed);
        previousCursor = query.cursor();
        previous = result;
        return result;
    }
}
