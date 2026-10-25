package io.github.campione01.mineclientbridge;
import java.util.UUID;
public final class PlayerGenerationChecks {
 private static int checks;
 private static void check(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
 private static final class Hostile {
  public boolean equals(Object other){throw new AssertionError("equals invoked");}
  public int hashCode(){throw new AssertionError("hashCode invoked");}
 }
 private static boolean frame(Object[] f){return PlayerGeneration.frameCurrent(f[0],f[1],f[2],f[3],f[4],f[5],f[6],f[7],f[8],f[9],f[10]);}
 public static void main(String[]args){
  Object a=new Hostile(),b=new Hostile();
  check(PlayerGeneration.current(null)==null);check(!PlayerGeneration.matches(null,"x"));
  String first=PlayerGeneration.current(a);check(first.equals(UUID.fromString(first).toString()));
  check(PlayerGeneration.matches(a,first));check(PlayerGeneration.current(a).equals(first));
  check(!PlayerGeneration.matches(b,first));check(!PlayerGeneration.matches(a,null));
  String second=PlayerGeneration.current(b);check(!first.equals(second));check(PlayerGeneration.matches(b,second));
  check(PlayerGeneration.current(a).equals(first));check(PlayerGeneration.matches(a,first));
  check(PlayerGeneration.current(null)==null);check(PlayerGeneration.current(a).equals(first));
  check(!PlayerGeneration.matches(a,second));
  for(int i=0;i<32;i++){Object next=new Hostile();String token=PlayerGeneration.current(next);check(!token.equals(first));check(PlayerGeneration.matches(next,token));}
  Object level=new Hostile(),server=new Hostile(),data=new Hostile(),uuid=new Hostile(),other=new Hostile();
  Object[] frame={a,a,level,level,level,server,server,data,data,uuid,uuid};
  check(frame(frame));
  for(int i=0;i<frame.length;i++){Object old=frame[i];frame[i]=other;check(!frame(frame));frame[i]=old;}
  for(int i:new int[]{0,2,7,9}){Object old=frame[i];frame[i]=null;check(!frame(frame));frame[i]=old;}
  System.out.println("PlayerGeneration checks="+checks);
 }
}
