package io.github.campione01.mineclientbridge;

import java.lang.ref.WeakReference;
import java.util.UUID;

/** Read-only, process-local identity for one private integrated server, independent of ClientLevel.
 * Never exposes a save path/name. Client disconnect invalidates it even if an object survives. */
final class IntegratedServerIdentity {
    private static WeakReference<Object> server=new WeakReference<>(null);
    private static String identity;
    static synchronized String current(Object instance,boolean privateWorld) {
        if(instance==null||!privateWorld) {clear();return null;}
        if(server.get()!=instance) {server=new WeakReference<>(instance);identity=UUID.randomUUID().toString();}
        return identity;
    }
    static synchronized void clear() {server.clear();identity=null;}
    private IntegratedServerIdentity() {}
}
