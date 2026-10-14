package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static io.github.campione01.mineclientbridge.WireV1Fixture.*;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Real production witness/projection/HTTP codec with synthetic captured facts only. */
public final class CombinedWireChecks {
    static int checks;
    static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
    static void write(Path out,String name,JsonObject body)throws Exception{
        Files.writeString(out.resolve(name),BridgeJson.toJson(body),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
    }
    static JsonObject makeAction(JsonObject scope,JsonObject intent,JsonObject facts){
        JsonObject compiled=intent.deepCopy();compiled.add("capability_guard",guard(TICK,NANO));
        JsonObject witness=ScopedNativePreflight.serializeWitness(scope,ACTION,SESSION,7,SERVER,
            ScopedNativePreflight.digest(intent),ScopedNativePreflight.digest(compiled),TICK,NANO,ADMITTED,facts,intent.getAsJsonObject("capability_guard"));
        ClientActionRequest command=new ClientActionRequest(ACTION,intent.get("action").getAsString(),intent.get("timeout_ms").getAsLong(),
            List.of(new ClientActionRequest.Point(12.5,64,24.5,false)),null,null,null,-1,false,false,-1,-1,0,null,compiled);
        ActionRegistry.Entry entry=new ActionRegistry.Entry(command);entry.result.add("scoped_native_preflight",witness);
        entry.result.addProperty("world_generation",WORLD);JsonObject action=entry.json(true);action.addProperty("action_session",SESSION);
        JsonObject budget=new JsonObject();budget.addProperty("active",false);budget.add("reason",JsonNull.INSTANCE);action.add("movement_budget",budget);
        return action;
    }
    static void emit(Path out,String name,JsonObject scope,JsonObject intent,JsonObject facts)throws Exception{
        JsonObject action=makeAction(scope,intent,facts),original=action.deepCopy();
        JsonObject standalone=actionEndpoint(action,false),coherent=capability(action);
        check(action.equals(original),name+" emitters must not mutate admission input");
        String a=BridgeJson.toJson(standalone),c=BridgeJson.toJson(coherent);
        check(a.getBytes(StandardCharsets.UTF_8).length<=262144 && c.getBytes(StandardCharsets.UTF_8).length<=262144,name+" real cap unchanged");
        JsonObject parsedA=JsonParser.parseString(a).getAsJsonObject(),parsedC=JsonParser.parseString(c).getAsJsonObject();
        JsonObject witness=parsedA.getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS);
        check(witness.equals(parsedC.getAsJsonObject("action").getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS)),name+" standalone/coherent witness equality after actual serialization");
        if(name.equals("collect")){
            check(parsedC.has(ScopedMovementWire.MARKER),"collect single-authority marker");
            for(String sibling:List.of("status","state")){
                var result=parsedC.getAsJsonObject(sibling).getAsJsonObject("client_action").getAsJsonObject("result");
                check(!result.has(ScopedMovementWire.WITNESS) && result.has(ScopedMovementWire.REFERENCE),"collect reference-only sibling "+sibling);
            }
            var rows=witness.getAsJsonObject("facts").getAsJsonObject("movement").getAsJsonObject("entity_guard").getAsJsonArray("rows");
            for(JsonElement row:rows){var flags=row.getAsJsonObject().getAsJsonObject("flags");check(flags.has("mob_target_uuid")&&flags.get("mob_target_uuid").isJsonNull(),"collect complete row preserves explicit null target");}
        } else {
            check(!parsedC.has(ScopedMovementWire.MARKER),"combat keeps supported inline witness contract");
            for(String sibling:List.of("status","state"))check(witness.equals(parsedC.getAsJsonObject(sibling).getAsJsonObject("client_action").getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS)),"combat complete inline sibling "+sibling);
        }
        write(out,name+"-standalone.json",standalone);write(out,name+"-coherent.json",coherent);
        write(out,name+"-request.json",scope);write(out,name+"-intent.json",intent);
    }
    public static void main(String[] args)throws Exception{
        Path out=Path.of(args[0]);if(!Files.isDirectory(out))throw new IllegalArgumentException("existing exclusive output directory required");
        try(var files=Files.list(out)){check(files.findAny().isEmpty(),"wire output must start empty");}
        String uuid="12345678-1234-1234-1234-123456789abc",fp="12345678-1234-1234-1234-123456789def";
        V p=new V(12.5,64,24.5),velocity=new V(0,0,0);Box b=new Box(12.375,64,24.375,12.625,64.25,24.625);
        var item=new Row(7,uuid,"minecraft:item",CLASSES.get("minecraft:item"),false,p,b,velocity,p,
            new Flags(false,true,false,false,false,false,false,false,0,0,null),project(b,p,velocity,p,160));
        var frame=new Frame(TICK,NANO+50_000,160,1,WireV1Facts.PRISM,List.of(item,WireV1Facts.far(10,"minecraft:sheep")),uuid);
        JsonObject target=point(12.5,64,24.5);target.addProperty("uuid",uuid);target.addProperty("entity_id",7);target.addProperty("item_id","minecraft:coal");target.addProperty("count",3);target.addProperty("item_fingerprint",fp);target.addProperty("component_fingerprint",fp);
        JsonObject scope=request(),original=intent(),f=facts(frame);scope.addProperty("profile",ScopedCollectTarget.PROFILE);original.add("pickup_target",target.deepCopy());
        JsonObject movement=f.getAsJsonObject("movement");movement.addProperty("profile",ScopedCollectTarget.PROFILE);target.addProperty("simple_components",true);target.addProperty("on_ground",true);target.addProperty("resting_envelope",PICKUP_RESTING_ENVELOPE);movement.add("pickup_target",target);
        emit(out,"collect",scope,original,f);

        scope=request();scope.addProperty("profile",ScopedCombat.PROFILE);original=intent();
        for(String key:List.of("waypoints","capability_route","jump","sneak","sprint"))original.remove(key);
        original.addProperty("action","combat_entity");original.addProperty("target_entity_id",9);original.addProperty("target_uuid","44444444-4444-4444-8444-444444444444");original.addProperty("target_type","minecraft:zombie");original.addProperty("approach",true);original.addProperty("shield",true);original.addProperty("min_health",14);original.addProperty("expected_hotbar_slot",0);
        f=facts(entities(List.of()));f.remove("movement");
        JsonObject sword=emptyStack();sword.addProperty("id","minecraft:iron_sword");sword.addProperty("count",1);sword.addProperty("empty",false);sword.addProperty("max_stack_size",1);
        f.getAsJsonArray("inventory").get(0).getAsJsonObject().add("item",sword.deepCopy());f.getAsJsonObject("equipment").add("mainhand",sword.deepCopy());f.getAsJsonObject("menu").getAsJsonArray("slots").get(36).getAsJsonObject().add("item",sword.deepCopy());original.add("expected_held_item",sword.deepCopy());
        JsonObject combat=point(14.5,64,25.5);combat.addProperty("profile",ScopedCombat.PROFILE);combat.addProperty("target_health",20.0);combat.addProperty("alive",true);
        for(String key:List.of("target_entity_id","target_uuid","target_type","approach","shield","min_health","timeout_ms"))combat.add(key,original.get(key).deepCopy());
        f.add("combat",combat);ScopedCombat.validateIntent(original);emit(out,"combat",scope,original,f);

        JsonObject mining=new JsonObject(),result=new JsonObject(),witness=new JsonObject(),miningFacts=new JsonObject(),miningFootprint=new JsonObject();
        var mr=MiningObservedPolicyTest.row("minecraft:sheep",new ScopedMiningEntityPolicy.V(40,64,24),new ScopedMiningEntityPolicy.V(0,0,0));
        miningFootprint.add("entity_guard",MiningObservedPolicyTest.one(mr).json());miningFacts.add("mining",miningFootprint);witness.addProperty("profile",ScopedMining.PROFILE);witness.add("facts",miningFacts);result.add(ScopedMovementWire.WITNESS,witness);mining.add("result",result);write(out,"mining-policy-input.json",mining);
        JsonObject report=new JsonObject();report.addProperty("checks",checks);report.addProperty("scope","Real production witness/assembly/projection/codec, explicitly synthetic captured facts. No game, mixin application, combat effects or pickup evidence.");write(out,"JAVA-WIRE-RESULT.json",report);
        System.out.println("PASS CombinedWireChecks "+checks+" checks; synthetic captured facts, real codec bytes");
    }
}
