package io.github.campione01.mineclientbridge;

/** Load pure computation types at bridge startup, never execute a plan or access a world. */
final class RetreatClassInitialization {
    static void initialize() {
        for (Class<?> type : new Class<?>[]{CombatRetreatWindow.class, CombatRetreatPolicy.class,
                CombatRetreatDiagnostics.class, CombatCellCache.class, FlatStepCorridor.class,
                CombatThreats.class, CombatSpatial.class, CombatDetour.class,
                CombatRouteEnvelope.class, CombatRouteMotion.class}) initialize(type);
    }

    private static void initialize(Class<?> type) {
        try {
            Class.forName(type.getName(), true, type.getClassLoader());
            for (Class<?> nested : type.getDeclaredClasses()) initialize(nested);
        } catch (ClassNotFoundException impossible) {
            throw new IllegalStateException("retreat computation class unavailable", impossible);
        }
    }

    private RetreatClassInitialization() { }
}
