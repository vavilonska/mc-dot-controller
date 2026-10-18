package io.github.campione01.mineclientbridge;

/** Dependency-free, one-click/one-send call-stack state. Reentrant checks fail closed. */
final class InventoryRecoveryBoundary {
    private boolean checking, clicked, sent;
    void click(Runnable check) {
        require(!checking && !clicked && !sent);
        guarded(check); clicked=true;
    }
    void send(Runnable check) {
        require(!checking && clicked && !sent);
        guarded(check); sent=true;
    }
    void after(Runnable check) {
        require(!checking && clicked && sent); guarded(check);
    }
    private void guarded(Runnable check) {
        checking=true;
        try { check.run(); } finally { checking=false; }
    }
    private static void require(boolean condition) {
        if(!condition)throw new IllegalStateException("inventory_recovery_boundary_unconfirmed");
    }
}
