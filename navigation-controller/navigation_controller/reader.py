"""Read-only paged collection over caller-supplied functions; no HTTP client."""
from .terrain import TerrainAssembler, TerrainError, integer


def collect_terrain(fetch_page, read_world, clock, *, radius=4, vertical=2,
                    max_pages=32, max_seconds=3.0):
    """Fetch only a bounded local cuboid, pacing pages by at least 50 ms.

    fetch_page(path) and read_world() are supplied explicitly. Any timeout, 409,
    429 or other read failure aborts; no retry creates competing scans. Another
    consumer starting a scan may invalidate this one. Never hold input while
    collecting. The caller must decide if observations are fresh for its action.
    """
    radius = integer(radius, 0, 16)
    vertical = integer(vertical, 0, 8)
    world = read_world()
    assembler = TerrainAssembler(world, clock.monotonic(), max_pages=max_pages,
                                 max_scan_seconds=max_seconds)
    path = f'/control/terrain?radius={radius}&vertical={vertical}&limit=128'
    while True:
        if not 0 <= clock.monotonic() - assembler.started_at < max_seconds:
            raise TerrainError('scan_wall_budget_exhausted')
        if assembler.pages >= max_pages:
            raise TerrainError('scan_page_budget_exhausted')
        assembler.add(fetch_page(path), clock.monotonic())
        if assembler.complete:
            return assembler.finish(read_world(), clock.monotonic())
        clock.sleep(0.05)
        path = '/control/terrain?cursor=' + assembler.next_cursor
