package io.github.campione01.mineclientbridge;
import java.util.function.Supplier;
/** Final external query, then pure exact arguments; poison any mismatch or reentry. */
final class ItemInteractionArgumentFence {
    private boolean checking,poisoned;
    void check(Runnable finalQuery,Supplier<TypedBoundaryPolicy> exactArguments){
        try{
            if(checking||poisoned)throw new IllegalStateException("item_interaction_argument_fence_reentered_or_poisoned");
            checking=true;
            try{
                TypedBoundaryPolicy before=exactArguments.get();
                if(before==null)throw new IllegalStateException("item_interaction_argument_frame_missing");
                finalQuery.run();
                TypedBoundaryPolicy after=exactArguments.get();
                if(poisoned||!before.same(after))throw new IllegalStateException("item_interaction_arguments_changed_after_final_query");
            }finally{checking=false;}
        }catch(RuntimeException failed){poisoned=true;throw failed;}
    }
}
