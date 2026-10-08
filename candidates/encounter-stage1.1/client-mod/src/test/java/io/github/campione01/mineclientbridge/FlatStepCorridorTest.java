package io.github.campione01.mineclientbridge;

import org.junit.jupiter.api.Test;

/** Pure helper regressions, not live Minecraft collision/physics acceptance. */
class FlatStepCorridorTest {
    @Test void sampledDiagonalGeometry() { FlatStepCorridorChecks.sampledDiagonalGeometry(); }
    @Test void sampledOffCorridorGrassDoesNotBlock() { FlatStepCorridorChecks.sampledOffCorridorGrassDoesNotBlock(); }
    @Test void reflectedReversedAndSwappedSweeps() { FlatStepCorridorChecks.reflectedReversedAndSwappedSweeps(); }
    @Test void forwardBackwardAxisAlignedAndStationary() { FlatStepCorridorChecks.forwardBackwardAxisAlignedAndStationary(); }
    @Test void squareFootprintNotCircle() { FlatStepCorridorChecks.squareFootprintNotCircle(); }
    @Test void tangenciesAndOutwardEpsilon() { FlatStepCorridorChecks.tangenciesAndOutwardEpsilon(); }
    @Test void middleOnlyCellsNeedSupport() { FlatStepCorridorChecks.middleOnlyCellsNeedSupport(); }
    @Test void middleWaterRejectedAtEveryLayer() { FlatStepCorridorChecks.middleWaterRejectedAtEveryLayer(); }
    @Test void middleLavaRejectedAtEveryLayer() { FlatStepCorridorChecks.middleLavaRejectedAtEveryLayer(); }
    @Test void middleUnknownAndUnloadedRejected() { FlatStepCorridorChecks.middleUnknownAndUnloadedRejected(); }
    @Test void middleHazardsRejectedAtEveryLayer() { FlatStepCorridorChecks.middleHazardsRejectedAtEveryLayer(); }
    @Test void middleFeetAndHeadCollisionsRejected() { FlatStepCorridorChecks.middleFeetAndHeadCollisionsRejected(); }
    @Test void fractionalFeetRequireIntegerTolerance() { FlatStepCorridorChecks.fractionalFeetRequireIntegerTolerance(); }
    @Test void invalidPoseAndStepFailBeforeAnyRead() { FlatStepCorridorChecks.invalidPoseAndStepFailBeforeAnyRead(); }
    @Test void readFailuresAndIncompleteFactsFailClosed() { FlatStepCorridorChecks.readFailuresAndIncompleteFactsFailClosed(); }
    @Test void preciseEvidenceAndAllThreeLayers() { FlatStepCorridorChecks.preciseEvidenceAndAllThreeLayers(); }
    @Test void deterministicSweepContainsDensePathReference() { FlatStepCorridorChecks.deterministicSweepContainsDensePathReference(); }
}
