package io.github.campione01.mineclientbridge;

/** Synchronous release-only identity, never a second gameplay owner or reusable permit. */
final class ScopedTerminalCleanupScope {
    static final class Token {
        final Object owner,entry; final long revision;
        Token(Object owner,Object entry,long revision){this.owner=owner;this.entry=entry;this.revision=revision;}
    }
    private Token token;
    Token enter(Object owner,Object entry,long revision){
        if(token!=null || owner==null || entry==null)throw new IllegalStateException("scoped_cleanup_busy_or_missing_owner");
        return token=new Token(owner,entry,revision);
    }
    boolean active(){return token!=null;}
    boolean bound(Object owner,Object entry,long revision,Object currentOwner,Object currentEntry){
        Token t=token;return t!=null && t.owner==owner && t.entry==entry && t.revision==revision
            && currentOwner==null && currentEntry==entry;
    }
    void close(Token expected){if(token!=expected)throw new IllegalStateException("scoped_cleanup_token_changed");token=null;}
}
