package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.*;
public final class OrdinaryMonotonicGuardChecks {
 static int passed;
 static void check(boolean value,String name){if(!value)throw new AssertionError(name);passed++;System.out.println("PASS "+name);}
 static void reject(Runnable r,String name){try{r.run();throw new AssertionError("admitted: "+name);}catch(ClientActionRequest.Rejected denied){passed++;System.out.println("PASS "+name+" -> "+denied.getMessage());}}
 static ObservationClientClock.Context context(String world){return new ObservationClientClock.Context(new Object(),new Object(),new Object(),new Object(),new Object(),"run",42,"server",world,"minecraft:the_nether","00000000-0000-0000-0000-000000000002","00000000-0000-0000-0000-000000000003");}
 static JsonObject request(JsonObject guard){var b=JsonParser.parseString("{\"action_id\":\"new-once\",\"action\":\"break_block\",\"target\":{\"x\":1,\"y\":64,\"z\":2},\"timeout_ms\":3000,\"expected_world_generation\":\"world\",\"expected_player_uuid\":\"player\",\"expected_action_session\":\"session\",\"expected_dimension\":\"minecraft:the_nether\",\"expected_hotbar_slot\":0,\"expected_held_item\":{\"item_fingerprint\":\"item\"},\"expected_block_id\":\"minecraft:netherrack\"}").getAsJsonObject();b.add("capability_guard",guard);return b;}
 public static void main(String[] args){
  var c=context("00000000-0000-0000-0000-000000000001");String generation="00000000-0000-0000-0000-000000000004";
  var source=new ObservationClientClock.Stamp(generation,20,1,c);var current=new ObservationClientClock.Stamp(generation,25,1,c);long nano=100;
  CapabilityGuard.requireMonotonicFresh(source.json(),nano,current,nano+800_000_000,"guard_start");check(true,"inclusive 5 client ticks / 800ms");
  // World gameTime is deliberately absent from the monotonic admission path.
  for(long gameTime:new long[]{3412409,3412405,3412425,0}){CapabilityGuard.requireMonotonicFresh(source.json(),nano,current,nano+158_000_000,"guard_start");check(true,"world time sync value does not affect monotonic ticket: "+gameTime);}
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,new ObservationClientClock.Stamp(generation,26,1,c),nano+1,"guard_start"),"6 client ticks");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,current,nano+800_000_001,"guard_start"),"800ms plus one ns");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,current,nano-1,"guard_start"),"future nano");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,new ObservationClientClock.Stamp(generation,19,1,c),nano+1,"guard_start"),"future client count");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,new ObservationClientClock.Stamp("00000000-0000-0000-0000-000000000005",25,1,c),nano+1,"guard_start"),"different epoch");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,new ObservationClientClock.Stamp(generation,25,2,c),nano+1,"guard_start"),"different clock origin");
  reject(()->CapabilityGuard.requireMonotonicFresh(source.json(),nano,new ObservationClientClock.Stamp(generation,25,1,context("00000000-0000-0000-0000-000000000006")),nano+1,"guard_start"),"different full context");
  var malformed=source.json();malformed.remove("count");reject(()->CapabilityGuard.requireMonotonicFresh(malformed,nano,current,nano+1,"guard_start"),"malformed source");
  var wrongContract=source.json();wrongContract.addProperty("contract","other");reject(()->CapabilityGuard.requireMonotonicFresh(wrongContract,nano,current,nano+1,"guard_start"),"wrong clock contract");
  CapabilityGuard.requireFresh(nano,100,nano+800_000_000,105,"guard_start");check(true,"schema1 original inclusive boundary");
  reject(()->CapabilityGuard.requireFresh(nano,100,nano+1,99,"guard_start"),"schema1 still rejects world tick reversal");
  reject(()->CapabilityGuard.requireFresh(nano,100,nano+1,106,"guard_start"),"schema1 still rejects over5");
  reject(()->CapabilityGuard.requireFresh(nano,100,nano+800_000_001,100,"guard_start"),"schema1 still rejects over800ms");
  var guard=new JsonObject();guard.addProperty("schema_version",2);guard.add("source_clock",source.json());guard.addProperty("source_nano",Long.toString(nano));
  check(ClientActionRequest.parse(request(guard)).action().equals("break_block"),"actual schema2 request parser");
  check(ClientActionRequest.parse(request(CapabilityGuard.observation(100,nano))).action().equals("break_block"),"actual schema1 request parser unchanged");
  var badSchema=guard.deepCopy();badSchema.addProperty("schema_version",3);reject(()->ClientActionRequest.parse(request(badSchema)),"unknown schema");
  var scoped=request(guard);scoped.addProperty("capability_descent",true);reject(()->ClientActionRequest.parse(scoped),"schema2 not silently admitted to scoped descent");
  var clock=new ObservationClientClock(()->generation,1000);clock.register();Object pre=new Object(),post=new Object();clock.pre(pre,c,1,true);clock.post(post,c,true);var observed=clock.sample(c,true);clock.pre(new Object(),c,2,true);clock.post(new Object(),c,true);check(clock.sample(c,true).count()==observed.count()+1,"existing native Pre/Post clock increments independently");
  System.out.println("TOTAL "+passed+" focused checks PASS; no game entrypoint invoked");
 }
}
