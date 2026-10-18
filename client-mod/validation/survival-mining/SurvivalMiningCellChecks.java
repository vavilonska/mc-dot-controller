package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Actual closed-cell policy and HTTP serializer; supplied game facts are synthetic. */
final class SurvivalMiningCellChecks {
    static int checks;
    static void check(boolean b,String message){checks++;if(!b)throw new AssertionError(message);}
    static JsonObject props(String text){return JsonParser.parseString(text).getAsJsonObject();}
    public static void main(String[]args)throws Exception{
        Path in=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectory(out);
        for(String kind:List.of("oak","spruce","birch","jungle","acacia","dark_oak"))for(String axis:List.of("x","y","z")){
            String id="minecraft:"+kind+"_log";JsonObject p=props("{\"axis\":\""+axis+"\"}");
            check(ScopedMiningCellPolicy.target(id,p),"exact log target");
            check(ScopedMiningCellPolicy.accepts(id,"net.minecraft.world.level.block.RotatedPillarBlock",p),"exact log class");
            check(!ScopedMiningCellPolicy.accepts(id,"net.minecraft.world.level.block.Block",p),"wrong log class");
            check(!ScopedMiningCellPolicy.target(id,new JsonObject()),"missing log axis");
        }
        for(String id:List.of("minecraft:iron_ore","minecraft:deepslate_iron_ore")){
            check(ScopedMiningCellPolicy.target(id,new JsonObject()),"iron target");
            check(ScopedMiningCellPolicy.accepts(id,"net.minecraft.world.level.block.DropExperienceBlock",new JsonObject()),"iron exact class");
        }
        for(String id:List.of("minecraft:coal_ore","minecraft:deepslate_coal_ore","minecraft:diamond_ore","minecraft:bamboo","minecraft:gravel","minecraft:wither_rose"))
            check(!ScopedMiningCellPolicy.target(id,new JsonObject()),"unavailable target "+id);
        for(String p:List.of("{}","{\"axis\":true}","{\"axis\":1}","{\"axis\":null}","{\"axis\":\"Y\"}","{\"axis\":\"y\",\"extra\":\"x\"}"))
            check(!ScopedMiningCellPolicy.target("minecraft:jungle_log",props(p)),"malformed log "+p);
        for(String p:List.of("{\"distance\":\"8\",\"persistent\":\"false\",\"waterlogged\":\"false\"}",
                "{\"distance\":\"1\",\"persistent\":\"false\",\"waterlogged\":\"true\"}",
                "{\"distance\":1,\"persistent\":\"false\",\"waterlogged\":\"false\"}"))
            check(!ScopedMiningCellPolicy.accepts("minecraft:jungle_leaves","net.minecraft.world.level.block.LeavesBlock",props(p)),"malformed/wet leaves");
        check(!ScopedMiningCellPolicy.support("minecraft:jungle_leaves"),"leaf support excluded");
        check(!ScopedMiningCellPolicy.bodyClear("minecraft:jungle_leaves"),"leaf body excluded");
        check(!ScopedMiningCellPolicy.bodyClear("minecraft:vine"),"climbing body excluded");
        check(ScopedMiningCellPolicy.bodyClear("minecraft:short_grass"),"empty collision harmless body");
        check(!ScopedMiningCellPolicy.support("minecraft:short_grass"),"plant support excluded");
        check(!ScopedMiningCellPolicy.accepts("minecraft:wither_rose","net.minecraft.world.level.block.WitherRoseBlock",new JsonObject()),"harmful flower excluded");
        var paths=Files.list(in).filter(p->p.toString().endsWith("-native.json")).sorted().toList();
        for(Path path:paths){
            JsonObject nativeAction=JsonParser.parseString(Files.readString(path)).getAsJsonObject();
            var m=nativeAction.getAsJsonObject("result").getAsJsonObject("scoped_native_preflight").getAsJsonObject("facts").getAsJsonObject("mining");
            for(var element:m.getAsJsonArray("cells")){
                var row=element.getAsJsonObject();String id=row.get("id").getAsString();
                check(ScopedMiningCellPolicy.accepts(id,row.get("block_class").getAsString(),row.getAsJsonObject("properties")),"actual cell policy "+id);
                check(row.get("static_full_cube").getAsBoolean()==ScopedMiningCellPolicy.fullCube(id),"full-cube evidence "+id);
            }
            JsonObject before=nativeAction.deepCopy();String wire=BridgeJson.toJson(nativeAction);
            check(nativeAction.equals(before),"serialization nonmutating");
            check(JsonParser.parseString(wire).equals(nativeAction),"wire exact preservation");
            Files.writeString(out.resolve(path.getFileName()),wire,StandardOpenOption.CREATE_NEW);
        }
        JsonObject vocab=new JsonObject();for(String id:new TreeSet<>(ScopedMiningCellPolicy.CELLS)){
            JsonObject row=new JsonObject();row.addProperty("class",ScopedMiningCellPolicy.expectedClass(id));
            row.addProperty("target",ScopedMiningCellPolicy.TARGETS.contains(id));row.addProperty("full_cube",ScopedMiningCellPolicy.fullCube(id));
            row.addProperty("body_clear",ScopedMiningCellPolicy.bodyClear(id));row.addProperty("support",ScopedMiningCellPolicy.support(id));vocab.add(id,row);
        }
        Files.writeString(out.resolve("vocabulary.json"),vocab.toString(),StandardOpenOption.CREATE_NEW);
        System.out.println("PASS "+checks+" production cell policy/HTTP checks across "+paths.size()+" synthetic witnesses; no native mining or gameplay");
    }
}
