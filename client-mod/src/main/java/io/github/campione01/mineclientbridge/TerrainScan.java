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
    // Leaves 32 KiB for response metadata inside the unchanged 256 KiB HTTP guard.
    static final int CAPABILITY_CELL_BYTES = 224 * 1024;

    enum Availability { LOADED, UNLOADED, OUT_OF_WORLD, READ_FAILED }
    interface Source<T> {
        Availability availability(int x, int y, int z);
        T readLoaded(int x, int y, int z);
        /** Exact/conservative serialized cell bytes, including an array separator. */
        default int encodedCellBytes(Cell<T> cell) { return 0; }
    }
    record Cell<T>(int x, int y, int z, Availability availability, T data) { }
    record Page<T>(String generation, int originX, int originY, int originZ,
            int radius, int vertical, int offset, int nextOffset, int total,
            List<Cell<T>> cells, String nextCursor, boolean budgetExhausted, long elapsedNanos,
            int pageLimit, boolean capability, boolean payloadBudgetExhausted) { }
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
    private boolean capability;
    private boolean observationClock;
    private Page<T> previous;
    private String previousCursor;

    TerrainScan(LongSupplier clock) { this.clock = clock; }

    /** Same native clock and actual-start history as page(); never a reservation. */
    boolean eligible(long now) {
        if (!hasRead) return true;
        long elapsed = now - lastRead;
        if (elapsed < 0) throw new Failure(409, "acquisition_clock_invalid");
        return elapsed >= MIN_PAGE_INTERVAL_NANOS;
    }

    long lastActualStart() {
        if (!hasRead) throw new IllegalStateException("terrain_has_no_start");
        return lastRead;
    }

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
            if(query.observationClock()!=observationClock) {clear();throw new Failure(409,"terrain_clock_profile_changed");}
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
            capability = query.capability();
            observationClock = query.observationClock();
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
        boolean payloadBudgetExhausted = false;
        int cellBytes = 0;
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
            Cell<T> cell = new Cell<>(cx, cy, cz, availability, data);
            if (capability) {
                int size;
                try { size = source.encodedCellBytes(cell); }
                catch (RuntimeException exception) {
                    clear();
                    throw new Failure(500, "terrain_cell_encoding_failed");
                }
                if (size < 0 || size > CAPABILITY_CELL_BYTES) {
                    clear();
                    throw new Failure(500, "terrain_cell_too_large");
                }
                if (size > CAPABILITY_CELL_BYTES - cellBytes) {
                    // Discard the boundary read. The unchanged offset is freshly read on
                    // continuation, never cached into a later page's sampling tick.
                    payloadBudgetExhausted = true;
                    break;
                }
                cellBytes += size;
            }
            cells.add(cell);
            offset++;
        }
        long elapsed = clock.getAsLong() - now;
        if (elapsed >= PAGE_BUDGET_NANOS && offset < total) budgetExhausted = true;
        Page<T> result = new Page<>(generation, originX, originY, originZ, radius, vertical,
                start, offset, total, List.copyOf(cells), offset < total ? generation + ":" + offset : null,
                budgetExhausted, elapsed, limit, capability, payloadBudgetExhausted);
        previousCursor = query.cursor();
        previous = result;
        return result;
    }
}
