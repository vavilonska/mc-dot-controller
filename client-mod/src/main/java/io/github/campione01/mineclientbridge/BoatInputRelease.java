package io.github.campione01.mineclientbridge;

/** Best-effort release of both owned input layers; never emits a braking command. */
final class BoatInputRelease {
 @FunctionalInterface interface Sink {void set(boolean left,boolean right,boolean up,boolean down);}
 static void clear(Sink boat,Sink player) {
  RuntimeException failure=null;
  try {boat.set(false,false,false,false);}catch(RuntimeException e){failure=e;}
  try {player.set(false,false,false,false);}catch(RuntimeException e){if(failure==null)failure=e;else failure.addSuppressed(e);}
  if(failure!=null)throw failure;
 }
 private BoatInputRelease() { }
}
