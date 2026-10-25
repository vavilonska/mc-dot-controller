package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.lang.reflect.*;

/** Runs the actual native request parser, native DTO builder and production HTTP byte serializer offline. */
public final class RecoveryShortInputWireChecks {
    static int checks;
    static void check(boolean ok,String what){if(!ok)throw new AssertionError(what);checks++;}
    static void rejects(String body){try{RecoveryShortInputCodec.parse(body.getBytes(StandardCharsets.UTF_8));throw new AssertionError("accepted "+body);}catch(IllegalArgumentException expected){checks++;}}
    public static void main(String[] args)throws Exception{
        Path out=Path.of(args[0]);Files.createDirectories(out);
        var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);
        Field field=NativeRecoveryShortInput.class.getDeclaredField("ledger");field.setAccessible(true);field.set(null,l);
        JsonObject request=new JsonObject();request.addProperty("schema_version",1);request.addProperty("profile",RecoveryShortInputLedger.PROFILE);
        request.addProperty("id","66666666-6666-4666-8666-666666666666");request.addProperty("session",l.session);request.addProperty("owner_id",RecoveryShortInputChecks.OWNER);request.addProperty("owner_generation",1);
        request.addProperty("world_generation",RecoveryShortInputChecks.WORLD);request.addProperty("player_uuid",RecoveryShortInputChecks.PLAYER);
        request.addProperty("forward",1.0);request.addProperty("strafe",0.0);request.addProperty("samples",2);request.addProperty("jump_first",true);request.addProperty("ttl_ms",500);request.addProperty("observation_id",RecoveryShortInputChecks.OBS);
        byte[] requestBytes=RecoveryShortInputCodec.encode(request);Files.write(out.resolve("request.json"),requestBytes);
        Method parse=NativeRecoveryShortInput.class.getDeclaredMethod("parseStart",JsonObject.class);parse.setAccessible(true);
        var r=(RecoveryShortInputLedger.Request)parse.invoke(null,RecoveryShortInputCodec.parse(requestBytes));var e=l.submit(r);
        Files.write(out.resolve("status-queued.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));
        check(l.sample(e,1,true,()->{}),"sample");l.stop(e,"explicit_stop");l.release(e,true,()->{},true,"explicit_stop");
        JsonObject terminal=NativeRecoveryShortInput.describe(e);Files.write(out.resolve("status-settled.json"),RecoveryShortInputCodec.encode(terminal));
        check(terminal.get("protocol_terminal").getAsBoolean()&&terminal.get("applied_samples").getAsInt()==1,"known_partial_protocol_terminal");
        check(terminal.get("settlement_state").getAsString().equals("not_observed"),"no_physical_settlement_claim");
        byte[] nulls=RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describeNoWorld(false,true));Files.write(out.resolve("observe-no-world.json"),nulls);
        String text=new String(nulls,StandardCharsets.UTF_8);check(text.contains("\"pose\":null")&&text.contains("\"world_generation\":null")&&text.contains("\"active_id\":null"),"actual_nullable_observation_fields_preserved");
        JsonObject zeroRequest=request.deepCopy();zeroRequest.addProperty("id","77777777-7777-4777-8777-777777777777");zeroRequest.addProperty("owner_generation",2);
        var rz=(RecoveryShortInputLedger.Request)parse.invoke(null,zeroRequest);var zero=l.submit(rz);l.rejectQueued(zero,"observation_stale_or_moved");
        Files.write(out.resolve("request-zero.json"),RecoveryShortInputCodec.encode(zeroRequest));
        Files.write(out.resolve("status-zero.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(zero)));
        check(zero.settled()&&zero.applied==0&&zero.released&&!zero.effectFenced,"stale_observation_known_no_input");
        rejects("{\"id\":\"a\",\"id\":\"b\"}");rejects("{\"x\":[]}");rejects("{\"x\":null}");rejects("{\"x\":1}{}");rejects("{\"x\":NaN}");
        JsonObject bad=request.deepCopy();bad.addProperty("samples",true);
        try{parse.invoke(null,bad);throw new AssertionError("boolean_as_number");}catch(InvocationTargetException expected){check(expected.getCause() instanceof IllegalArgumentException,"strict_numeric_type");}
        System.out.println("RecoveryShortInputWireChecks PASS assertions="+checks+" fixture_dir="+out);
    }
}
