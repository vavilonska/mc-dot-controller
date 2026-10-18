package io.github.campione01.mineclientbridge;

import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
/** Exact setter owner; releases and truthful getter state are never suppressed. */
public final class ManagedNavigationInputPolicy {
    static final class Token {
        final Object input;final BooleanSupplier permit;volatile boolean quarantined,bridgeClosed;
        Token(Object input,BooleanSupplier permit){this.input=input;this.permit=permit;}
    }
    private static volatile Token owner;
    private static volatile boolean admissionOpen;
    private static final AtomicReference<String> blocked=new AtomicReference<>();
    static synchronized void openAdmission(){admissionOpen=true;}
    static synchronized Token closeAdmission(){
        admissionOpen=false;Token captured=owner;if(captured!=null){captured.bridgeClosed=true;captured.quarantined=true;}return captured;
    }
    static boolean bridgeClosed(Token expected){return expected!=null&&expected.bridgeClosed;}
    static boolean shutdownOwns(Token expected,Token current){return expected!=null&&expected==current&&expected.bridgeClosed;}
    static boolean admissionOpen(){return admissionOpen;}
    static synchronized Token claim(Object input,BooleanSupplier permit){
        if(!admissionOpen||owner!=null||input==null||permit==null)throw new IllegalStateException("managed_navigation_input_owner_conflict");
        blocked.set(null);Token next=new Token(input,permit);owner=next;return next;
    }
    static synchronized void quarantine(Token expected){if(owner==expected&&expected!=null)expected.quarantined=true;}
    static synchronized void settled(Token expected){if(owner!=expected||expected==null)throw new IllegalStateException("managed_navigation_input_owner_changed");owner=null;}
    static boolean movementOwner(boolean exact,boolean customActive,Object observed,Object expected){
        return exact&&customActive&&observed==expected;
    }
    static String blockedReason(){return blocked.get();}
    public static boolean reject(Object input,String key){
        Token captured=owner;if(captured==null)return false;
        if(key.equals("CLICK_LEFT")||key.equals("CLICK_RIGHT")){
            blocked.compareAndSet(null,"managed_navigation_door_or_nonwalking_input_blocked");return true;
        }
        boolean allowed=false;
        try{allowed=admissionOpen&&input==captured.input&&!captured.quarantined&&captured.permit.getAsBoolean();}
        catch(RuntimeException|LinkageError unavailable){allowed=false;}
        if(!allowed||!admissionOpen||owner!=captured||captured.quarantined){
            blocked.compareAndSet(null,"managed_navigation_input_owner_unproven");return true;
        }
        return false;
    }
    private ManagedNavigationInputPolicy(){}
}
