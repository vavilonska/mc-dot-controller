package io.github.campione01.mineclientbridge;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class CapabilityUseTransitionTest {
    @Test void ordinaryUseAndReleaseCanConfirmOnlyAfterCallbacksReturn() {
        var transition=new CapabilityUseTransition();int[] calls={0};
        transition.run(()->calls[0]++);assertTrue(transition.cleanupMayConfirm());
        transition.run(()->calls[0]++);assertTrue(transition.cleanupMayConfirm());assertEquals(2,calls[0]);
    }
    @Test void takeoverDuringUseOrReleaseLatchesUncertaintyEvenIfOldCallResumes() {
        for(String operation:new String[]{"offhand_useItem","releaseUsingItem"}) {
            var transition=new CapabilityUseTransition();boolean[] continued={false};
            transition.run(()->{assertFalse(transition.cleanupMayConfirm(),operation);continued[0]=true;});
            assertTrue(continued[0]);assertFalse(transition.cleanupMayConfirm(),operation);
            assertThrows(IllegalStateException.class,()->transition.run(()->fail("must never replay or renew")));
        }
    }
    @Test void caughtNestedAttemptStillLatchesUnknownAndCannotReplay() {
        var transition=new CapabilityUseTransition();int[] calls={0};
        transition.run(()->{
            calls[0]++;
            assertThrows(IllegalStateException.class,()->transition.run(()->calls[0]++));
        });
        assertEquals(1,calls[0]);assertFalse(transition.cleanupMayConfirm());
        assertThrows(IllegalStateException.class,()->transition.run(()->calls[0]++));
        assertEquals(1,calls[0]);
    }
    @Test void bowUseAndReleaseCancellationCannotConfirmCleanup() {
        for(String operation:new String[]{"mainhand_useItem","bow_releaseUsingItem"}) {
            var transition=new CapabilityUseTransition();int[] effects={0};
            transition.run(()->{effects[0]++;assertFalse(transition.cleanupMayConfirm(),operation);});
            assertFalse(transition.cleanupMayConfirm(),operation);
            assertThrows(IllegalStateException.class,()->transition.run(()->effects[0]++));
            assertEquals(1,effects[0]);
        }
    }
    @Test void thrownSideEffectCannotBecomeKnownNoEffect() {
        var transition=new CapabilityUseTransition();
        assertThrows(IllegalStateException.class,()->transition.run(()->{throw new IllegalStateException("uncertain effect");}));
        assertFalse(transition.cleanupMayConfirm());
    }
}
