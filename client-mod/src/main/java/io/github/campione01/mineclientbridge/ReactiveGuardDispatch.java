package io.github.campione01.mineclientbridge;

/** The production pre-tick ownership branch, injectable only as Java callbacks for offline tests. */
final class ReactiveGuardDispatch {
 interface Host {
  boolean hasOwner(); boolean interruptAllowed(); boolean physicalReady();
  boolean cancelExactOriginal(); void startNewProtection(); void waiting(String reason);
 }
 static void tick(Host host){
  if(host.hasOwner()){
   if(host.interruptAllowed()&&host.cancelExactOriginal())host.waiting("original_cancelled_wait_cleanup");
   else host.waiting("active_owner_not_interruptible");
   return; // Never start inside the cancellation/cleanup stack, even when it succeeded.
  }
  if(!host.physicalReady()){host.waiting("physical_release_not_proven");return;}
  host.startNewProtection();
 }
 private ReactiveGuardDispatch(){}
}
