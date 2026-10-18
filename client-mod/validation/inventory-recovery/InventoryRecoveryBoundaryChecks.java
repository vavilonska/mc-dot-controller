package io.github.campione01.mineclientbridge;
/** Executes the production boundary, with synthetic owner/state checks and no game classes. */
public final class InventoryRecoveryBoundaryChecks {
    static int assertions;
    static void reject(Runnable action){assertions++;try{action.run();throw new AssertionError("expected rejection");}catch(IllegalStateException expected){}}
    static Runnable noop=()->{};
    public static void main(String[]args){
        for(int i=0;i<100;i++){
            var normal=new InventoryRecoveryBoundary();reject(()->normal.send(noop));reject(()->normal.after(noop));
            normal.click(noop);reject(()->normal.click(noop));normal.send(noop);normal.after(noop);reject(()->normal.send(noop));
            var before=new InventoryRecoveryBoundary();reject(()->before.click(()->{throw new IllegalStateException("owner cancelled");}));reject(()->before.send(noop));
            var after=new InventoryRecoveryBoundary();after.click(noop);reject(()->after.send(()->{throw new IllegalStateException("changed window/cursor/owner/freshness");}));reject(()->after.after(noop));
            var recursive=new InventoryRecoveryBoundary();reject(()->recursive.click(()->recursive.click(noop)));reject(()->recursive.send(noop));
            var sendRecursive=new InventoryRecoveryBoundary();sendRecursive.click(noop);reject(()->sendRecursive.send(()->sendRecursive.send(noop)));reject(()->sendRecursive.after(noop));
            var captureRecursive=new InventoryRecoveryBoundary();captureRecursive.click(noop);captureRecursive.send(noop);reject(()->captureRecursive.after(()->captureRecursive.send(noop)));
            var late=new InventoryRecoveryBoundary();late.click(noop);late.send(noop);reject(()->late.after(()->{throw new IllegalStateException("late owner replacement");}));
        }
        System.out.println("production_boundary_assertions="+assertions+" live_gameplay=false");
    }
}
