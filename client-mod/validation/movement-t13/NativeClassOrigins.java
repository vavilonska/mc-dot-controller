package io.github.campione01.mineclientbridge;
import java.nio.file.Path;
/** Loads metadata without initializing game or bridge classes. */
public final class NativeClassOrigins {
 public static void main(String[] args)throws Exception {
  Path expected=Path.of(args[0]).toRealPath();
  for(String name:new String[]{"BridgeServer","CapabilitySnapshot","ClientActionRequest","ClientActions","ScopedFlatMovement","ScopedMovementEntities","ScopedMovementWire","ActionRegistry","BridgeJson","ScopedNativePreflight","ScopedEntityPolicy","ScopedFlatPolicy"}) {
   Class<?> type=Class.forName("io.github.campione01.mineclientbridge."+name,false,NativeClassOrigins.class.getClassLoader());
   Path actual=Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
   if(!actual.equals(expected))throw new AssertionError("Not the fresh production output: "+name);
   System.out.println("PASS fresh production origin "+name);
  }
 }
}
