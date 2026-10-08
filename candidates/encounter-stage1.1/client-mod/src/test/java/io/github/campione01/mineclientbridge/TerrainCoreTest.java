package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
class TerrainCoreTest {
    @Test void boundedReadOnlyScanContract() { TerrainCoreChecks.run(); }
    @Test void dispatchAdmissionSurvivesTimeouts() throws Exception { TerrainDispatchChecks.run(); }
}
