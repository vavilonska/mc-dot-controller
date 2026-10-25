"""Offline adapter sketch; neither this file nor TerrainMemory sends game input."""
from terrain_memory import MemoryError


def ingest_complete_window(memory, pages_with_receive_times):
    """Pages come from the existing reader, not from a new competing scanner."""
    scan = None
    for page, received_at in pages_with_receive_times:
        if scan is None:
            scan = memory.begin_scan(received_at=received_at)
        scan.add(page, received_at=received_at)
    if scan is None:
        raise MemoryError("no_pages")
    return scan.commit()  # Missing pages raise; previous memory is untouched.


def candidate_for_existing_planner(memory, start, goal, *, fresh_guard):
    """Illustrative consumer seam, NOT execution permission.

    fresh_guard is caller-owned: it must freshly observe/revalidate the relevant
    next segment, loaded chunks, support, collision, fluid and live threats.
    A successful result still goes through the existing native dispatch/owner/
    movement guard. Do not turn a historical route into a fresh TerrainGrid.
    """
    routes = memory.candidate_routes(start, goal)
    if not routes:
        return None
    candidate = routes[0]
    if fresh_guard(candidate) is not True:
        raise MemoryError("fresh_guard_refused")
    return candidate  # Still historical, revalidation_required=True.


if __name__ == "__main__":
    from terrain_memory import Context, TerrainMemory
    context = Context("11111111-1111-4111-8111-111111111111", "minecraft:the_nether")
    memory = TerrainMemory(context)
    memory.remember_walked([(0, 64, 0), (1, 64, 0)], context=context,
                          evidence_id="offline-synthetic-walk", observed_at=10.0)
    # Demonstrate refusal despite remembering that this corridor was walked.
    try:
        candidate_for_existing_planner(memory, (0, 64, 0), (1, 64, 0), fresh_guard=lambda route: False)
    except MemoryError as refusal:
        print(refusal)
    print(memory.summary())
