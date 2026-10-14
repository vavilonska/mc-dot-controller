package io.github.campione01.mineclientbridge;
import java.util.List;
import java.nio.file.*;
import com.google.gson.*;
import static io.github.campione01.mineclientbridge.ScopedMiningEntityPolicy.*;
final class MiningObservedPolicyTest {
 static int checks;
 static void check(boolean b){checks++;if(!b)throw new AssertionError();}
 static void reject(Runnable r){checks++;try{r.run();}catch(IllegalArgumentException expected){return;}throw new AssertionError("not refused");}
 static final Box PRISM=new Box(11,63,23,16,67,26);
 static Row row(String type,V p,V velocity){boolean living=!type.equals("minecraft:item");Box b=new Box(p.x()-.125,p.y(),p.z()-.125,p.x()+.125,p.y()+.25,p.z()+.125);return new Row(42,"33333333-3333-4333-8333-333333333333",type,CLASSES.get(type),false,p,b,velocity,p,new Flags(living,true,false,false,false,false,false,false,0,0,null),project(b,p,velocity,p,160));}
 static Frame one(Row row){return frame(400,1000000,160,1,PRISM,List.of(row));}
 public static void main(String[] args)throws Exception{
  V zero=new V(0,0,0);Row sheep=row("minecraft:sheep",new V(40,64,24),zero);
  check(one(sheep).population()==2);
  reject(()->one(row("minecraft:sheep",new V(14,64,24),zero)));
  reject(()->one(row("minecraft:sheep",new V(40,64,24),new V(-.2,0,0))));
  Row item=row("minecraft:item",new V(14,64,24),zero);
  check(one(item).rows().get(0).json().get("verdict").getAsString().equals("passive_item"));
  reject(()->row("minecraft:arrow",new V(40,64,24),zero));
  reject(()->new V(Double.NaN,64,24));
  reject(()->frame(400,1000000,161,1,PRISM,List.of(sheep)));
  reject(()->frame(400,1000000,160,1,PRISM,List.of(sheep,sheep)));
  JsonObject nativeAction=JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
  JsonObject before=nativeAction.deepCopy();String wire=BridgeJson.toJson(nativeAction);
  check(nativeAction.equals(before));
  JsonObject decoded=JsonParser.parseString(wire).getAsJsonObject();
  JsonObject flags=decoded.getAsJsonObject("result").getAsJsonObject("scoped_native_preflight").getAsJsonObject("facts").getAsJsonObject("mining").getAsJsonObject("entity_guard").getAsJsonArray("rows").get(0).getAsJsonObject().getAsJsonObject("flags");
  check(flags.has("mob_target_uuid") && flags.get("mob_target_uuid").isJsonNull());
  Files.writeString(Path.of(args[1]),wire,StandardOpenOption.CREATE_NEW);
  System.out.println("PASS "+checks+" production policy/serializer checks; no engine execution");
 }
}
