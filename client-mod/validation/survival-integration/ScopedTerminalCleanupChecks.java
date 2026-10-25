package io.github.campione01.mineclientbridge;

/** Finite checks against the actual synchronous cleanup scope, with identity-only owners. */
public final class ScopedTerminalCleanupChecks {
    static int checks;
    static void check(boolean yes,String label){checks++;if(!yes)throw new AssertionError(label);}
    static void refuses(Runnable action,String label){checks++;try{action.run();}catch(IllegalStateException expected){return;}throw new AssertionError(label);}
    public static void main(String[] args){
        ScopedTerminalCleanupScope scope=new ScopedTerminalCleanupScope();
        Object owner=new Object(),entry=new Object();long revision=17;
        check(!scope.active(),"starts inactive");
        check(!scope.bound(owner,entry,revision,null,entry),"no uninstalled permission");
        refuses(()->scope.enter(null,entry,revision),"missing owner refused");
        refuses(()->scope.enter(owner,null,revision),"missing entry refused");
        ScopedTerminalCleanupScope.Token token=scope.enter(owner,entry,revision);
        check(scope.active(),"synchronous scope active");
        check(!scope.bound(owner,entry,revision,owner,entry),"not ordinary active owner authority");
        check(scope.bound(owner,entry,revision,null,entry),"exact detached owner cleanup");
        check(!scope.bound(new Object(),entry,revision,null,entry),"owner replacement refused");
        check(!scope.bound(owner,new Object(),revision,null,entry),"entry replacement refused");
        check(!scope.bound(owner,entry,revision+1,null,entry),"revision replacement refused");
        check(!scope.bound(owner,entry,revision,new Object(),entry),"successor active refused");
        check(!scope.bound(owner,entry,revision,null,new Object()),"registry replacement refused");
        check(!scope.bound(owner,entry,revision,null,null),"registry disappearance refused");
        refuses(()->scope.enter(new Object(),new Object(),revision),"nested scope refused");
        check(scope.bound(owner,entry,revision,null,entry),"nested refusal preserves original");
        scope.close(token);
        check(!scope.active()&&!scope.bound(owner,entry,revision,null,entry),"closed scope never authorizes");
        ScopedTerminalCleanupScope.Token replacement=scope.enter(owner,entry,revision+1);
        refuses(()->scope.close(token),"old token cannot close replacement");
        check(scope.bound(owner,entry,revision+1,null,entry),"replacement retained after stale close");
        scope.close(replacement);
        check(!scope.active(),"replacement closed exactly");
        System.out.println("ScopedTerminalCleanupChecks PASS checks="+checks);
    }
}
