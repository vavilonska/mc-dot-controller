package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;

/** Synchronous old-owner release scope. Never an input owner or an effect permit. */
final class FallRescueCleanupScope {
    static final class Token {
        final Object owner,guard,entry;
        final BooleanSupplier bound;
        boolean closed,invalid;
        Token(Object owner,Object guard,Object entry,BooleanSupplier bound){
            this.owner=owner;this.guard=guard;this.entry=entry;this.bound=bound;
        }
        boolean live(){
            if(closed||invalid)return false;
            try {if(!bound.getAsBoolean())invalid=true;}
            catch(RuntimeException refused){invalid=true;}
            return !invalid;
        }
    }
    /** Foreign channels must stay absent; this scope never releases or cancels them. */
    static boolean channelsAbsent(boolean rawHeld,int isolatedHeld,Object guardedOwner){
        return !rawHeld&&isolatedHeld==0&&guardedOwner==null;
    }
    private Token current;
    Token open(Object owner,Object guard,Object entry,BooleanSupplier bound){
        if(current!=null||owner==null||entry==null||bound==null)
            throw new IllegalStateException("fall_rescue_recursive_or_invalid_cleanup_scope");
        return current=new Token(owner,guard,entry,bound);
    }
    boolean active(){return current!=null;}
    boolean permits(Object guard,Object entry){
        Token token=current;
        return token!=null&&guard!=null&&token.guard==guard&&token.entry==entry&&token.live()&&current==token;
    }
    boolean bound(Object owner,Object entry){
        Token token=current;
        return token!=null&&token.owner==owner&&token.entry==entry&&token.live()&&current==token;
    }
    void close(Token token){
        if(token==null)return;
        token.closed=true;
        if(current==token)current=null;
    }
}
