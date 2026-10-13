# Container observation slice — offline PASS, platform gates unmet

Baseline: reviewed mainline handoff r4 source ZIP adcc0075d534d993c0411d1b8ec80dafafc5a463e28f08831143566a3128da54. No Java from the newer moving candidate tree was imported.

Production consists of exact frozen v18 BoundedContainerSnapshot.java plus three additive BridgeServer calls: screen/menu snapshot budget resets, and bounded nonempty item metadata. The budget remains shared across a full observation: at most four expanded shulker boxes, 27 slots per box, 128 characters per custom name, no recursive containers or arbitrary component serialization. The five legacy empty fields and existing nonempty id/count/damage/max_damage remain.

Both complete v18 cross-slice classes (IntegratedCandidateContractTest and ExpeditionPrerequisitesContractTest) now run, closing their prior container deferral. One transitional MainlineCombatSliceTest assertion changes from expecting the container call absent to present. Other existing test assertions are unchanged.

Fresh execution on 2026-10-09, one serial window 04:02:54–04:03:49 UTC:
- Finite kit: 86 assertions pass, source pins and two reset-hook checks pass. It executes the exact helper and extracted production itemSnapshot method with configured types; this is not MC registration/menu-runtime proof.
- Default --offline test build --rerun-tasks: BUILD SUCCESSFUL in 21s; 603 discovered, 596 passed, 7 gated tests skipped and explicitly unmet.
- Explicit MDC_REAL_MOD_LOADER_TESTS=true probe: BUILD FAILED in 7s, one initialization failure before the seven methods. Actual NeoForge FeatureFlagLoader cannot dereference LoadingModList.get()==null during Bootstrap. XML/log retained. No fake loader or lifecycle was supplied; these seven gates are not passed.

client-mod/build/test-results was overwritten by the deliberate lifecycle probe, so the complete successful default XML is preserved separately as container-default-xml. The failed probe is container-real-gate-xml. The built production JAR excludes finite fixture classes.

The platform acceptance document specifies the genuine-loader, read-only inventory/container verification still needed. No game, deployment, remote branch or Library mutation occurred. The main environment recovery, watchdog/cursor and stable-result capabilities are retained; this slice does not close all MDC mainline integration. Pause producer is a separate not-yet-tested overlay and is absent from this packet.
