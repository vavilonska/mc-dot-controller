package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import static io.github.campione01.mineclientbridge.WireV1Fixture.*;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Real production assembler/projection/serializer, synthetic captured facts. No engine. */
final class WireV1ProducerCases {
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);}
    static int bytes(JsonObject body)throws Exception{return BridgeJson.toJson(body).getBytes(StandardCharsets.UTF_8).length;}
    static void write(Path path,JsonObject body)throws Exception{
        Files.writeString(path,BridgeJson.toJson(body),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
    }
    static JsonObject actionWithRows(int count) {
        var rows=new ArrayList<Row>();
        for(int i=0;i<count;i++)rows.add(i==2?WireV1Facts.removed(i):WireV1Facts.far(i,i==1?"minecraft:boat":"minecraft:sheep"));
        JsonObject action=action(entities(rows));action.addProperty("status","succeeded");action.addProperty("input_owner","direct");
        action.getAsJsonObject("result").addProperty("input_release_confirmed",true);return action;
    }
    static JsonObject legacyInline(JsonObject projected) {
        JsonObject out=projected.deepCopy();out.remove(ScopedMovementWire.MARKER);
        JsonObject witness=out.getAsJsonObject("action").getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS);
        for(String name:List.of("status","state")){
            var result=out.getAsJsonObject(name).getAsJsonObject("client_action").getAsJsonObject("result");
            result.remove(ScopedMovementWire.REFERENCE);result.add(ScopedMovementWire.WITNESS,witness.deepCopy());
        }
        return out;
    }
    static JsonObject pad(JsonObject body,int target)throws Exception {
        JsonObject padded=body.deepCopy();padded.addProperty("synthetic_size_padding","");
        int remaining=target-bytes(padded);check(remaining>=0,"padding only grows synthetic body");
        padded.addProperty("synthetic_size_padding","界".repeat(remaining/3)+"x".repeat(remaining%3));
        check(bytes(padded)==target,"exact UTF8 byte boundary");return padded;
    }
    static void rejected(int one,int coherent) {
        try{requireResponseSizes(one,coherent,262144);throw new AssertionError("expected size refusal");}
        catch(IllegalArgumentException bad){check(bad.getMessage().equals("scoped_movement_response_evidence_too_large"),"known size reason");}
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=1 || !Files.isDirectory(Path.of(args[0])))throw new IllegalArgumentException("Exclusive existing output directory required");
        Path out=Path.of(args[0]);
        try(var existing=Files.list(out)){check(existing.findAny().isEmpty(),"exclusive fixture directory must start empty");}
        JsonArray sizes=new JsonArray();
        for(int count:new int[]{0,3,32,64,128,180}) {
            JsonObject action=actionWithRows(count),before=action.deepCopy();
            JsonObject standalone=actionEndpoint(action,false),coherent=capability(action);
            check(action.equals(before),"production projection never mutates action input");
            check(coherent.get(ScopedMovementWire.MARKER).getAsString().equals(ScopedMovementWire.ENCODING),"declared marker");
            JsonObject inline=legacyInline(coherent);
            check(ScopedMovementWire.project(inline).equals(coherent),"shared actual and preview projection");
            int one=bytes(standalone),single=bytes(coherent),three=bytes(inline);
            JsonObject row=new JsonObject();row.addProperty("nonself_rows",count);row.addProperty("standalone_bytes",one);
            row.addProperty("single_authority_bytes",single);row.addProperty("legacy_three_copy_bytes",three);
            boolean allowed=true;try{requireResponseSizes(one,single,262144);}catch(IllegalArgumentException bad){allowed=false;}
            row.addProperty("fits_reserved_budget",allowed);sizes.add(row);
            check(single<three,"lossless witness reference representation saves bytes");
            write(out.resolve("coherent-"+count+".json"),coherent);write(out.resolve("standalone-"+count+".json"),standalone);
            write(out.resolve("legacy-inline-"+count+".json"),inline);
        }
        write(out.resolve("original-intent.json"),intent());write(out.resolve("original-request.json"),request());
        JsonObject action=actionWithRows(3),standalone=actionEndpoint(action,false),coherent=capability(action);
        var one=pad(standalone,253952);var both=pad(coherent,237568);
        requireResponseSizes(bytes(one),bytes(both),262144);
        var oneOver=one.deepCopy();oneOver.addProperty("synthetic_size_padding",oneOver.get("synthetic_size_padding").getAsString()+"x");
        var bothOver=both.deepCopy();bothOver.addProperty("synthetic_size_padding",bothOver.get("synthetic_size_padding").getAsString()+"x");
        check(bytes(oneOver)==253953 && bytes(bothOver)==237569,"actual serialized threshold plus one");
        rejected(bytes(oneOver),bytes(both));rejected(bytes(one),bytes(bothOver));
        write(out.resolve("coherent-at-reserved-limit.json"),both);
        write(out.resolve("standalone-at-reserved-limit.json"),one);
        var diagnostics=ScopedMovementWire.sizeDiagnostic(action,bytes(one),bytes(bothOver),262144);
        var response=BridgeServer.ActionResponses.result(()->{throw new ClientActionRequest.Rejected(409,
            "scoped_movement_response_evidence_too_large",null,diagnostics);},true);
        check(response.status()==409,"real error wrapper keeps known409");write(out.resolve("size-refusal.json"),response.body());
        for(String profile:List.of("state-menu-v1","state-use-v1","block-menu-v1","movement-flat-v1")) {
            JsonObject legacy=action.deepCopy();legacy.getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS).addProperty("profile",profile);
            for(JsonObject body:List.of(actionEndpoint(legacy,false),capability(legacy))) {
                check(!body.has(ScopedMovementWire.MARKER),"legacy marker absent");
                check(BridgeJson.toJson(body).equals(LegacyBridgeJsonReference.toJson(body)),"legacy wire bytes unchanged");
            }
        }
        JsonObject report=new JsonObject();report.addProperty("scope","Synthetic captured facts; actual production assembler/projection/serializer; no game or native dispatch");
        report.add("representative_cases",sizes);report.addProperty("original_T10_witness_available",false);
        report.addProperty("request_cap_bytes",65536);report.addProperty("response_cap_bytes",262144);
        report.addProperty("standalone_reserved_threshold",253952);report.addProperty("coherent_reserved_threshold",237568);
        write(out.resolve("producer-case-sizes.json"),report);
        JsonArray files=new JsonArray();
        try(var paths=Files.list(out)) {
            for(Path file:paths.sorted().toList()) {
                byte[] raw=Files.readAllBytes(file);JsonObject pin=new JsonObject();
                pin.addProperty("path",file.getFileName().toString());pin.addProperty("bytes",raw.length);
                pin.addProperty("sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw)));files.add(pin);
            }
        }
        JsonObject manifest=new JsonObject();manifest.addProperty("schema","mdc.movement-wire-fixtures/1");manifest.add("files",files);
        write(out.resolve("FIXTURE-MANIFEST.json"),manifest);
    }
    private WireV1ProducerCases() { }
}
