package io.github.campione01.mineclientbridge;
import java.util.*;
/** Differential check against the frozen TEST2.11 fence, copied under a test-only name. */
public final class FenceParityChecks {
 interface F {void raw();void check(Runnable r);void close();}
 static List<String> trace(boolean successor,int mode){
  var events=new ArrayList<String>();long[] now={100},tick={1};boolean[] owner={true},flip={false},throwTick={false};
  java.util.function.BooleanSupplier owns=()->{events.add("owner");return owner[0];};
  java.util.function.LongSupplier clock=()->{events.add("clock");return now[0];};
  java.util.function.LongSupplier ticks=()->{events.add("tick");if(throwTick[0])throw new IllegalStateException("reader_fault");if(flip[0])owner[0]=false;return tick[0];};
  F f;
  if(successor){var g=new CombatCallbackFence(owns,clock,ticks);f=new F(){public void raw(){g.raw();}public void check(Runnable r){g.check(r);}public void close(){g.close();}};}
  else {var g=new LegacyCombatCallbackFence(owns,clock,ticks);f=new F(){public void raw(){g.raw();}public void check(Runnable r){g.check(r);}public void close(){g.close();}};}
  Runnable mutate=()->{switch(mode){case 1->now[0]+=50_000_000L;case 2->now[0]+=50_000_001L;case 3->now[0]--;case 4->tick[0]++;case 5->owner[0]=false;case 6->flip[0]=true;case 7->throwTick[0]=true;case 8->f.close();case 9->f.check(()->events.add("nested"));case 10->throw new IllegalStateException("body_fault");case 11->now[0]=Long.MAX_VALUE;default->{}}};
  for(int pass=0;pass<2;pass++)try{if(pass==0)f.check(mutate);else f.raw();events.add("ok");}catch(RuntimeException e){events.add(e.getClass().getName()+":"+e.getMessage());}
  return events;
 }
 public static void main(String[] args){int n=0;for(int mode=0;mode<12;mode++){var a=trace(false,mode);var b=trace(true,mode);if(!a.equals(b))throw new AssertionError("mode "+mode+" old="+a+" new="+b);n++;}System.out.println("FenceParityChecks passed "+n+" exact owner/clock/tick call-order and outcome traces against frozen TEST2.11");}
}
