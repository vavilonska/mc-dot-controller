package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;

/** Pure callback fence used by native admission/effects; cancellation always wins. */
final class FallRescueFence {
    private long revision;
    long stamp(){return revision;}
    void changed(){revision++;}
    void commit(long expected){if(revision!=expected)throw new IllegalStateException("fall_rescue_operation_superseded");changed();}
    static boolean sameContext(Object arm,long operation,Object episode,Object currentArm,long currentOperation,Object currentEpisode){
        return arm==currentArm&&operation==currentOperation&&episode==currentEpisode;
    }
    static boolean afterHook(BooleanSupplier hook,BooleanSupplier owner){return hook.getAsBoolean()&&owner.getAsBoolean();}
}
