package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.HashSet;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Opt-in page capacity remains independent of the existing wall-time and rate limits. */
class TerrainCapabilityPageTest {
    private static TerrainScan.Source<String> known(AtomicLong reads) {
        return new TerrainScan.Source<>() {
            public TerrainScan.Availability availability(int x, int y, int z) {
                return TerrainScan.Availability.LOADED;
            }
            public String readLoaded(int x, int y, int z) {
                reads.incrementAndGet(); return x + ":" + y + ":" + z;
            }
        };
    }

    @Test void explicitCapabilityQueryAllows1024ButLegacyStillRejects129() {
        assertEquals(1024, TerrainQuery.parse("capability=1&limit=1024").limit());
        assertEquals(64, TerrainQuery.parse("capability=1").limit());
        assertEquals(128, TerrainQuery.parse("limit=128").limit());
        assertThrows(IllegalArgumentException.class, () -> TerrainQuery.parse("limit=129"));
        assertFalse(TerrainQuery.parse(null).capability());
        assertFalse(new TerrainQuery(8, 4, 64, null).capability());
        assertTrue(TerrainQuery.parse("capability=1").capability());
    }

    @Test void actualScanReturnsMoreThanLegacyLimitWhenBudgetAllows() {
        var reads = new AtomicLong();
        var scan = new TerrainScan<String>(() -> 0L);
        var page = scan.page(TerrainQuery.parse("radius=8&vertical=4&limit=1024&capability=1"),
                new Object(), 0, 64, 0, known(reads));
        assertEquals(1024, page.cells().size());
        assertEquals(1024, reads.get());
        assertEquals(1024, page.nextOffset());
        assertFalse(page.budgetExhausted());
        assertEquals(1024, page.pageLimit());
        assertTrue(page.capability());
        assertFalse(page.payloadBudgetExhausted());
    }

    @Test void malformedOptInNeverWidensLegacyOrCursorRequests() {
        String cursor = "00000000-0000-0000-0000-000000000000:1";
        for (String query : new String[]{"capability=0", "capability=2", "capability=01", "capability=true",
                "capability=", "capability=-1", "capability=1.0", "capability=1&capability=1",
                "capability=1&%63apability=1", "capability=%GG", "capability=1&limit=1025",
                "capability=1&limit=0", "capability=1&limit=10000", "capability=1&limit=1e3",
                "capability=1&radius=0001", "limit=0128", "capability=1&radius=17",
                "capability=1&vertical=9", "cursor=" + cursor + "&capability=1",
                "cursor=" + cursor + "&limit=1024"}) {
            assertThrows(IllegalArgumentException.class, () -> TerrainQuery.parse(query), query);
        }
    }

    @Test void completeCapabilityScanKeeps1024ProfileOriginAndExactCoverageAcrossCursors() {
        var time = new AtomicLong(); var reads = new AtomicLong(); var world = new Object();
        var scan = new TerrainScan<String>(time::get); Set<String> seen = new HashSet<>();
        var page = scan.page(TerrainQuery.parse("radius=16&vertical=8&limit=1024&capability=1"),
                world, -30, 64, -30, known(reads));
        int offset = 0;
        while (true) {
            assertEquals(offset, page.offset()); assertEquals(1024, page.pageLimit()); assertTrue(page.capability());
            assertTrue(page.cells().size() <= 1024); assertFalse(page.cells().isEmpty());
            assertEquals(-30, page.originX()); assertEquals(64, page.originY()); assertEquals(-30, page.originZ());
            for (var cell : page.cells()) assertTrue(seen.add(cell.data()));
            offset = page.nextOffset(); if (page.nextCursor() == null) break;
            time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
            page = scan.page(TerrainQuery.parse("cursor=" + page.nextCursor()), world, 999, 999, 999, known(reads));
        }
        assertEquals(TerrainQuery.MAX_BLOCKS, seen.size()); assertEquals(TerrainQuery.MAX_BLOCKS, reads.get());
    }

    @Test void capabilityStillRequires50msButMostRecentCursorReplayIsReadFree() {
        var time = new AtomicLong(); var reads = new AtomicLong(); var world = new Object();
        var scan = new TerrainScan<String>(time::get);
        var first = scan.page(TerrainQuery.parse("capability=1&limit=1024"), world, 0, 64, 0, known(reads));
        var cursor = TerrainQuery.parse("cursor=" + first.nextCursor());
        time.set(TerrainScan.MIN_PAGE_INTERVAL_NANOS - 1);
        assertEquals(429, assertThrows(TerrainScan.Failure.class, () -> scan.page(cursor, world, 0, 0, 0, known(reads))).status);
        time.incrementAndGet(); var second = scan.page(cursor, world, 0, 0, 0, known(reads));
        assertSame(second, scan.page(cursor, world, 0, 0, 0, known(reads))); assertEquals(2048, reads.get());
        assertTrue(second.capability()); assertEquals(1024, second.pageLimit());
        scan.clear();
        assertEquals(429, assertThrows(TerrainScan.Failure.class,
                () -> scan.page(TerrainQuery.parse("limit=128"), world, 0, 0, 0, known(reads))).status);
        time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
        var legacy = scan.page(TerrainQuery.parse("limit=128"), world, 0, 0, 0, known(reads));
        assertFalse(legacy.capability()); assertEquals(128, legacy.cells().size()); assertEquals(128, legacy.pageLimit());
        assertEquals(409, assertThrows(TerrainScan.Failure.class, () -> scan.page(cursor, world, 0, 0, 0, known(reads))).status);
    }

    @Test void sizingTimeIsInsideTheUnchangedTwoMillisecondBudget() {
        var time = new AtomicLong(); var reads = new AtomicLong();
        var source = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.LOADED; }
            public String readLoaded(int x, int y, int z) { reads.incrementAndGet(); return "observed"; }
            public int encodedCellBytes(TerrainScan.Cell<String> cell) { time.addAndGet(1_000_000L); return 10; }
        };
        var page = new TerrainScan<String>(time::get).page(TerrainQuery.parse("capability=1&limit=1024"), new Object(), 0, 64, 0, source);
        assertEquals(2, page.cells().size()); assertEquals(2, reads.get()); assertEquals(2, page.nextOffset());
        assertTrue(page.budgetExhausted()); assertFalse(page.payloadBudgetExhausted());
        assertEquals(2_000_000L, page.elapsedNanos()); assertEquals(2_000_000L, TerrainScan.PAGE_BUDGET_NANOS);
        assertEquals(50_000_000L, TerrainScan.MIN_PAGE_INTERVAL_NANOS);
    }

    @Test void byteBoundaryDiscardsAndFreshlyRereadsTheSameUnadvancedCoordinate() {
        var time = new AtomicLong(); var reads = new AtomicLong(); var world = new Object();
        var source = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.LOADED; }
            public String readLoaded(int x, int y, int z) { return x + ":read:" + reads.incrementAndGet(); }
            public int encodedCellBytes(TerrainScan.Cell<String> cell) { return 100_000; }
        };
        var scan = new TerrainScan<String>(time::get);
        var first = scan.page(TerrainQuery.parse("radius=1&vertical=0&capability=1&limit=1024"), world, 0, 64, 0, source);
        assertEquals(2, first.cells().size()); assertEquals(2, first.nextOffset()); assertEquals(3, reads.get());
        assertTrue(first.payloadBudgetExhausted()); assertFalse(first.budgetExhausted());
        time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
        var cursor = TerrainQuery.parse("cursor=" + first.nextCursor());
        var second = scan.page(cursor, world, 100, 100, 100, source);
        assertEquals(2, second.offset()); assertEquals(1, second.cells().getFirst().x());
        assertEquals("1:read:4", second.cells().getFirst().data(), "The discarded prior tick's third read must not be cached");
        assertSame(second, scan.page(cursor, world, 100, 100, 100, source)); assertEquals(6, reads.get());
    }

    @Test void oversizedOrFailedCellEncodingFailsClosedWithoutPublishingAPage() {
        for (int size : new int[]{-1, TerrainScan.CAPABILITY_CELL_BYTES + 1}) {
            var time = new AtomicLong(); var world = new Object(); var scan = new TerrainScan<String>(time::get);
            var source = new TerrainScan.Source<String>() {
                public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.LOADED; }
                public String readLoaded(int x, int y, int z) { return "observed"; }
                public int encodedCellBytes(TerrainScan.Cell<String> cell) { return size; }
            };
            var error = assertThrows(TerrainScan.Failure.class,
                    () -> scan.page(TerrainQuery.parse("capability=1&limit=1024"), world, 0, 64, 0, source));
            assertEquals(500, error.status); assertEquals("terrain_cell_too_large", error.getMessage());
            assertEquals(429, assertThrows(TerrainScan.Failure.class,
                    () -> scan.page(TerrainQuery.parse("capability=1&limit=1024"), world, 0, 64, 0, source)).status);
        }
    }

    @Test void capabilityCursorStillInvalidatesOnWorldChangeExpiryAndDisconnect() {
        for (String event : new String[]{"world", "expiry", "disconnect"}) {
            var time = new AtomicLong(); var reads = new AtomicLong(); var world = new Object();
            var scan = new TerrainScan<String>(time::get);
            var first = scan.page(TerrainQuery.parse("capability=1&limit=1024"), world, 0, 64, 0, known(reads));
            var cursor = TerrainQuery.parse("cursor=" + first.nextCursor());
            time.addAndGet(event.equals("expiry") ? TerrainScan.MAX_AGE_NANOS : TerrainScan.MIN_PAGE_INTERVAL_NANOS);
            Object current = event.equals("world") ? new Object() : event.equals("disconnect") ? null : world;
            assertEquals(409, assertThrows(TerrainScan.Failure.class, () -> scan.page(cursor, current, 0, 64, 0, known(reads))).status);
            assertEquals(1024, reads.get(), event);
        }
    }

    @Test void capabilityUnknownCellsNeverBecomeLoadedReadsAndLegacyNeverCallsSizer() {
        var reads = new AtomicLong();
        var source = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.UNLOADED; }
            public String readLoaded(int x, int y, int z) { reads.incrementAndGet(); throw new AssertionError("unloaded read"); }
            public int encodedCellBytes(TerrainScan.Cell<String> cell) { assertNull(cell.data()); return 100; }
        };
        var page = new TerrainScan<String>(() -> 0L).page(TerrainQuery.parse("capability=1&limit=1024"), new Object(), 0, 64, 0, source);
        assertEquals(1024, page.cells().size()); assertEquals(0, reads.get());
        var legacy = new TerrainScan.Source<String>() {
            public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.READ_FAILED; }
            public String readLoaded(int x, int y, int z) { throw new AssertionError("unknown read"); }
            public int encodedCellBytes(TerrainScan.Cell<String> cell) { throw new AssertionError("Legacy sizer must not execute"); }
        };
        assertEquals(128, new TerrainScan<String>(() -> 0L).page(TerrainQuery.parse("limit=128"), new Object(), 0, 64, 0, legacy).cells().size());
    }
}
