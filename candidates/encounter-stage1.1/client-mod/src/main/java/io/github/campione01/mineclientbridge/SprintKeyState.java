package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Vanilla hold/toggle key transition; no settings changes or repeated toggle presses. */
final class SprintKeyState {
    static void set(BooleanSupplier down, Consumer<Boolean> setDown, boolean wanted) {
        if (down.getAsBoolean() == wanted) return;
        setDown.accept(wanted);
        // ToggleKeyMapping ignores false in toggle mode. One true transition
        // clears an existing toggle; never send true again while already on.
        if (!wanted && down.getAsBoolean()) setDown.accept(true);
        if (down.getAsBoolean() != wanted) throw new IllegalStateException("sprint_key_transition_unconfirmed");
    }
    private SprintKeyState() { }
}
