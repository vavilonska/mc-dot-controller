package io.github.campione01.mineclientbridge;

/** Tracks observed reference changes only; unseen away-and-back reuse is not detectable. */
final class ObservedMenuGeneration {
    private Object screen, list;
    private long generation = 1;
    private boolean seen;
    long current() { return generation; }
    long observe(Object currentScreen, Object currentList) {
        if (seen && (screen != currentScreen || list != currentList)) {
            WorldSelectionSnapshot.need(generation != Long.MAX_VALUE, "generation_overflow");
            generation++;
        }
        screen = currentScreen; list = currentList; seen = true;
        return generation;
    }
}
