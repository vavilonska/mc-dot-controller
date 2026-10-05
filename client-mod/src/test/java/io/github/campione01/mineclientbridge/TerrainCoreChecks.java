package io.github.campione01.mineclientbridge;

import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

/** Also runnable without Gradle/Minecraft/JUnit using the Java 21 compiler. */
public final class TerrainCoreChecks {
    private static int checks;
    public static void main(String[] args) { run(); }
    static void run() {
        checks = 0;
        queryBounds();
        worldGeneration();
        failedReadsStayUnknown();
        unloadedAndOutOfWorldNeverRead();
        pageBoundAndCoverage();
        cooperativeBudget();
        cursorLifetimeAndWorldInvalidation();
        rateLimitAndIdempotentRetry();
        System.out.println("Terrain core: " + checks + " checks passed");
    }
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static void invalid(String query) {
        try { TerrainQuery.parse(query); throw new AssertionError("Accepted " + query); }
        catch (IllegalArgumentException expected) { checks++; }
    }
    private static void failure(int status, Runnable call) {
        try { call.run(); throw new AssertionError("Expected status " + status); }
        catch (TerrainScan.Failure expected) { check(expected.status == status, expected.getMessage()); }
    }
    private static void worldGeneration() {
        Object world = new Object();
        String first = WorldGeneration.current(world);
        check(first != null && first.equals(WorldGeneration.current(world)), "stable world identity");
        check(!first.equals(WorldGeneration.current(new Object())), "new world identity");
        check(WorldGeneration.current(null) == null, "disconnect clears identity");
        check(!first.equals(WorldGeneration.current(world)), "reconnect changes identity");
    }
    private static void failedReadsStayUnknown() {
        TerrainScan<String> scan = new TerrainScan<>(() -> 0L);
        var source = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x,int y,int z) { return TerrainScan.Availability.LOADED; }
            public String readLoaded(int x,int y,int z) { throw new IllegalStateException("broken mod block"); }
        };
        var page = scan.page(TerrainQuery.parse("radius=0&vertical=0"),new Object(),0,0,0,source);
        check(page.cells().getFirst().availability() == TerrainScan.Availability.READ_FAILED, "read error explicit");
        check(page.cells().getFirst().data() == null && page.nextCursor() == null, "read error is unknown and scan advances");
    }
    private static void queryBounds() {
        TerrainQuery defaults = TerrainQuery.parse(null);
        check(defaults.radius() == 8 && defaults.vertical() == 4 && defaults.limit() == 64, "defaults");
        check(TerrainQuery.parse("radius=16&vertical=8&limit=128").limit() == 128, "maxima");
        check(TerrainQuery.parse("radius=0&vertical=0&limit=1").radius() == 0, "minima");
        for (String raw : new String[]{"radius=17", "vertical=9", "limit=129", "limit=0", "radius=-1",
                "radius=NaN", "radius=Infinity", "radius=1.5", "radius=2147483647", "radius=1&radius=2",
                "radius=1&%72adius=2", "radius=%GG", "x=20", "cursor=hello", "radius", "radius=", "&", "r".repeat(513),
                "cursor=00000000-0000-0000-0000-000000000000:0&limit=1"}) invalid(raw);
    }
    private static TerrainScan.Source<String> known(AtomicLong reads) {
        return new TerrainScan.Source<>() {
            public TerrainScan.Availability availability(int x,int y,int z) { return TerrainScan.Availability.LOADED; }
            public String readLoaded(int x,int y,int z) { reads.incrementAndGet(); return x + ":" + y + ":" + z; }
        };
    }
    private static void unloadedAndOutOfWorldNeverRead() {
        AtomicLong time = new AtomicLong(), reads = new AtomicLong();
        TerrainScan<String> scan = new TerrainScan<>(time::get);
        TerrainScan.Source<String> source = new TerrainScan.Source<>() {
            public TerrainScan.Availability availability(int x,int y,int z) {
                return y < 0 ? TerrainScan.Availability.OUT_OF_WORLD : x < 0 ? TerrainScan.Availability.UNLOADED : TerrainScan.Availability.LOADED;
            }
            public String readLoaded(int x,int y,int z) {
                check(x >= 0 && y >= 0, "No read of unknown terrain");
                reads.incrementAndGet(); return "minecraft:stone";
            }
        };
        var page = scan.page(TerrainQuery.parse("radius=1&vertical=1&limit=128"), new Object(), 0,0,0, source);
        check(page.cells().size() == 27, "volume");
        check(reads.get() == 12, "only loaded cells read");
        check(page.cells().stream().filter(c -> c.availability() != TerrainScan.Availability.LOADED).allMatch(c -> c.data() == null), "unknown stays unknown");
    }
    private static void pageBoundAndCoverage() {
        AtomicLong time = new AtomicLong(), reads = new AtomicLong();
        TerrainScan<String> scan = new TerrainScan<>(time::get);
        Object world = new Object();
        Set<String> coordinates = new HashSet<>();
        var query = TerrainQuery.parse("radius=16&vertical=8&limit=128");
        var page = scan.page(query,world, -30, 64,-30,known(reads));
        check(page.total() == TerrainQuery.MAX_BLOCKS, "hard volume bound");
        int offset = 0;
        while (true) {
            check(page.offset() == offset && page.cells().size() <= 128 && !page.cells().isEmpty(), "bounded contiguous page");
            for (var cell : page.cells()) {
                check(cell.x() >= -46 && cell.x() <= -14 && cell.z() >= -46 && cell.z() <= -14 && cell.y() >= 56 && cell.y() <= 72, "coordinate bounds");
                check(coordinates.add(cell.data()), "no duplicate");
            }
            offset = page.nextOffset();
            if (page.nextCursor() == null) break;
            time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
            page = scan.page(TerrainQuery.parse("cursor=" + page.nextCursor()),world,1000,200,1000,known(reads));
            check(page.originX() == -30 && page.originY() == 64 && page.originZ() == -30, "fixed anchor while player moves");
        }
        check(coordinates.size() == TerrainQuery.MAX_BLOCKS && reads.get() == TerrainQuery.MAX_BLOCKS, "complete volume exactly once");
    }
    private static void cooperativeBudget() {
        AtomicLong time = new AtomicLong(), reads = new AtomicLong();
        TerrainScan<String> scan = new TerrainScan<>(time::get);
        var source = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x,int y,int z) { return TerrainScan.Availability.LOADED; }
            public String readLoaded(int x,int y,int z) { reads.incrementAndGet(); time.addAndGet(1_000_000); return "x"; }
        };
        var page = scan.page(TerrainQuery.parse("limit=128"),new Object(),0,64,0,source);
        check(page.cells().size() == 2 && page.budgetExhausted(), "stop between cells at time budget");
        check(page.nextOffset() == 2 && page.nextCursor() != null, "budget retains continuation");
        check(page.elapsedNanos() == TerrainScan.PAGE_BUDGET_NANOS, "reported measured elapsed time");
    }
    private static void cursorLifetimeAndWorldInvalidation() {
        AtomicLong time = new AtomicLong(), reads = new AtomicLong(); Object world = new Object();
        TerrainScan<String> scan = new TerrainScan<>(time::get);
        var page = scan.page(TerrainQuery.parse("limit=1"),world,0,0,0,known(reads));
        TerrainQuery cursor = TerrainQuery.parse("cursor=" + page.nextCursor());
        time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
        failure(409, () -> scan.page(cursor,new Object(),0,0,0,known(reads)));
        check(reads.get() == 1, "world changed: no reads");
        page = scan.page(TerrainQuery.parse("limit=1"),world,0,0,0,known(reads));
        TerrainQuery expires = TerrainQuery.parse("cursor=" + page.nextCursor());
        time.addAndGet(TerrainScan.MAX_AGE_NANOS);
        failure(409, () -> scan.page(expires,world,0,0,0,known(reads)));
        failure(409, () -> scan.page(TerrainQuery.parse(null),null,0,0,0,known(reads)));
    }
    private static void rateLimitAndIdempotentRetry() {
        AtomicLong time = new AtomicLong(), reads = new AtomicLong(); Object world = new Object();
        TerrainScan<String> scan = new TerrainScan<>(time::get);
        var first = scan.page(TerrainQuery.parse("limit=1"),world,0,0,0,known(reads));
        TerrainQuery cursor = TerrainQuery.parse("cursor=" + first.nextCursor());
        failure(429, () -> scan.page(cursor,world,0,0,0,known(reads)));
        failure(429, () -> scan.page(TerrainQuery.parse(null),world,0,0,0,known(reads)));
        time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
        var second = scan.page(cursor,world,0,0,0,known(reads));
        check(scan.page(cursor,world,0,0,0,known(reads)) == second && reads.get() == 2, "repeat last cursor has zero reads");
        time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
        scan.page(TerrainQuery.parse(null),world,0,0,0,known(reads));
        failure(409, () -> scan.page(cursor,world,0,0,0,known(reads)));
    }
}
