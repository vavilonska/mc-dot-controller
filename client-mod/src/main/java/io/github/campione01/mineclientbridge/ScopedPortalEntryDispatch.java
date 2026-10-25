package io.github.campione01.mineclientbridge;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.level.block.Portal;
/** Non-cancelling vanilla contact observer; unrelated entities and unbound contacts are inert. */
public final class ScopedPortalEntryDispatch {
    private static boolean installed;
    private static ScopedPortalEntry bound;
    public static void installed(){installed=true;}
    static boolean ready(){return installed;}
    static void bind(ScopedPortalEntry guard){
        if(guard==null||!guard.activeBinding()||bound!=null&&bound!=guard&&bound.activeBinding())
            throw new IllegalStateException("portal_entry_contact_owner_changed");
        bound=guard;
    }
    static void unbind(ScopedPortalEntry guard){if(bound==guard)bound=null;}
    public static void contact(Entity actual,Portal portal,BlockPos cell){
        ScopedPortalEntry guard=bound;if(guard!=null)guard.contact(actual,portal,cell);
    }
    private ScopedPortalEntryDispatch(){}
}
