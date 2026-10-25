package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import net.minecraft.core.BlockPos;

/** Offline real-94 compatibility and v2 production codec checks; no Minecraft bootstrap or world. */
public final class RecoveryInteractionV2Checks {
    static final String V1=RecoveryShortInputLedger.INTERACTION_PROFILE,V2=RecoveryShortInputLedger.INTERACTION_V2_PROFILE;
    static final String PLAN="e".repeat(64);
    static int checks;
    static void check(boolean value,String label){if(!value)throw new AssertionError(label);checks++;}
    static void rejects(Runnable action,String label){try{action.run();throw new AssertionError(label);}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
    static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String id,String kind,int calls,String owner){
        var op=new RecoveryShortInputLedger.Operation(kind,kind.equals("look")?-180:0,0,kind.equals("select_hotbar")?2:0,kind.equals("select_hotbar")||kind.equals("break_block")?"b".repeat(64):"",kind.equals("break_block")?-635:0,kind.equals("break_block")?61:0,kind.equals("break_block")?16:0,kind.equals("break_block")?"SOUTH":"",kind.equals("break_block")?"minecraft:nether_wart_block":"",V2,1,PLAN);
        return new RecoveryShortInputLedger.Request(id,l.session,owner,l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,0,0,calls,false,2000,RecoveryShortInputChecks.OBS,op);
    }
    static JsonObject json(RecoveryShortInputLedger.Request r){
        JsonObject j=RecoveryInteractionChecks.requestJson(r);if(r.profile().equals(V2)){j.addProperty("plan_version",r.operation().planVersion());j.addProperty("plan_sha256",r.operation().planSha256());}return j;
    }
    static RecoveryShortInputLedger.Request parse(JsonObject j){return NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(RecoveryShortInputCodec.encode(j)),V2);}
    public static void main(String[] args)throws Exception{
        Path fixture=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);
        boundaries();crossProfile();typedPlanRoundtrip();history94(fixture,out);wire(out.resolve("wire-fixtures"));
        System.out.println("RecoveryInteractionV2Checks PASS assertions="+checks);
    }
    static void boundaries()throws Exception{
        var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);
        var move=json(request(l,"move","move",8,RecoveryShortInputChecks.OWNER));check(parse(move).samples()==8,"move8_still_allowed");
        var jump=move.deepCopy();jump.addProperty("jump_first",true);rejects(()->parse(jump),"v2_jump_rejected_at_actual_parser");
        var oldJump=jump.deepCopy();oldJump.addProperty("profile",V1);oldJump.remove("plan_version");oldJump.remove("plan_sha256");check(NativeRecoveryShortInput.parseInteractionStart(oldJump).jumpFirst(),"v1_jump_semantics_unchanged");
        var mining=json(request(l,"mining","break_block",32,RecoveryShortInputChecks.OWNER));check(parse(mining).operation().blockId().equals("minecraft:nether_wart_block"),"v2_exact_wart_allowed");
        for(String bad:List.of("minecraft:nether_wart","minecraft:warped_wart_block","minecraft:nether_bricks","minecraft:sand","minecraft:tnt","minecraft:chest")){
            JsonObject j=mining.deepCopy();j.addProperty("block_id",bad);rejects(()->parse(j),"no_material_tag_or_class_widening_"+bad);
        }
        var cobble=mining.deepCopy();cobble.addProperty("block_id","minecraft:cobblestone");check(parse(cobble).operation().blockId().equals("minecraft:cobblestone"),"v2_cobble_exact_allowed");
        var old=mining.deepCopy();old.addProperty("profile",V1);old.remove("plan_version");old.remove("plan_sha256");rejects(()->NativeRecoveryShortInput.parseInteractionStart(old),"v1_new_coords_rejected");old.addProperty("x",-636);old.addProperty("y",60);old.addProperty("z",33);rejects(()->NativeRecoveryShortInput.parseInteractionStart(old),"v1_wart_rejected_even_old_coord");old.addProperty("block_id","minecraft:cobblestone");check(NativeRecoveryShortInput.parseInteractionStart(old).profile().equals(V1),"v1_original_request_still_accepted");
        rejects(()->NativeRecoveryShortInput.parseInteractionStart(mining,V1),"v2_payload_v1_parser_route_rejected");rejects(()->NativeRecoveryShortInput.parseInteractionStart(old,V2),"v1_payload_v2_parser_route_rejected");
        check(!RecoveryInteraction.allowedTarget(V2,new BlockPos(-635,60,16),60),"v2_feet_layer_rejected");check(!RecoveryInteraction.allowedTarget(V2,new BlockPos(-635,59,16),60),"v2_below_feet_rejected");check(RecoveryInteraction.allowedTarget(V2,new BlockPos(-635,61,16),60),"v2_above_feet_not_absolute59");
        check(!RecoveryInteraction.allowedTarget(V1,new BlockPos(-635,61,16),60),"v1_original_coords_preserved");check(RecoveryInteraction.allowedTarget(V1,new BlockPos(-636,60,33),59),"v1_original_footheight_preserved");check(!RecoveryInteraction.allowedTarget(V1,new BlockPos(-636,60,33),58),"v1_other_footheight_rejected");
        for(String key:List.of("max_calls","ttl_ms")){var bad=mining.deepCopy();bad.addProperty(key,key.equals("max_calls")?33:2001);rejects(()->parse(bad),"unchanged_bound_"+key);}
        var noPlan=mining.deepCopy();noPlan.remove("plan_sha256");rejects(()->parse(noPlan),"v2_missing_plan_rejected");
        var wrongPlan=mining.deepCopy();wrongPlan.addProperty("plan_version",2);rejects(()->parse(wrongPlan),"plan_version_must_be1");
        var badHash=mining.deepCopy();badHash.addProperty("plan_sha256","E".repeat(64));rejects(()->parse(badHash),"plan_hash_lower_hex_required");
        var changedPlan=mining.deepCopy();changedPlan.addProperty("plan_sha256","f".repeat(64));check(!parse(changedPlan).digest().equals(parse(mining).digest()),"plan_digest_binds_hash");
        var oldWithPlan=old.deepCopy();oldWithPlan.addProperty("plan_version",1);oldWithPlan.addProperty("plan_sha256",PLAN);rejects(()->NativeRecoveryShortInput.parseInteractionStart(oldWithPlan),"old_profile_rejects_new_plan_keys");
        var extra=mining.deepCopy();extra.addProperty("batch",true);rejects(()->parse(extra),"closed_no_batch");
        check(new RecoveryShortInputLedger.Operation("move",0,0,0,"",0,0,0,"","").profile().equals(V1),"old_operation_constructor_defaults_v1");
    }
    static void crossProfile()throws Exception{
        var store=new RecoveryShortInputChecks.Memory();var now=new AtomicLong(100);var l=new RecoveryShortInputLedger(store,now::get);RecoveryInteractionChecks.setLedger(l);
        var old=RecoveryInteractionChecks.typed(l,"cross-id","look",1);var e=l.submit(old);l.rejectQueued(e,"offline_known_zero");
        var newOp=new RecoveryShortInputLedger.Operation("look",-180,-30,0,"",0,0,0,"","",V2,1,PLAN);
        var changed=new RecoveryShortInputLedger.Request(old.id(),old.session(),old.ownerId(),old.generation(),old.world(),old.player(),old.forward(),old.strafe(),old.samples(),old.jumpFirst(),old.ttlMs(),old.observationId(),newOp);
        check(!changed.digest().equals(old.digest()),"profile_bound_in_existing_utf_digest_prefix");rejects(()->l.submit(changed),"same_id_new_profile_not_replayable");
        rejects(()->NativeRecoveryShortInput.start(json(old),V1),"inactive_v1_start_rejected_in_v2_mode");
        var r=request(l,"active-v2","break_block",32,l.owner());var active=l.submit(r);check(l.submit(r)==active,"v2_duplicate_original_no_dispatch");
        var changedPlan=json(r);changedPlan.addProperty("plan_sha256","f".repeat(64));rejects(()->l.submit(parse(changedPlan)),"same_id_different_plan_rejected");
        l.stop(active,"explicit_stop");check(active.settled()&&!l.claimCall(active,1,true),"v2_queued_stop_no_call");
        var exp=l.submit(request(l,"expire-v2","break_block",32,l.owner()));now.addAndGet(2_000_000_000L);check(!l.claimCall(exp,2,true)&&exp.settled(),"v2_deadline_no_renew");
        var unfinished=l.submit(request(l,"unfinished-v2","break_block",32,l.owner()));check(l.claimCall(unfinished,3,true),"v2_entered_fence");
        var restarted=new RecoveryShortInputLedger(store,now::get,true);check(restarted.locked(),"v2_unfinished_restart_unknown");
        rejects(()->restarted.submit(RecoveryInteractionChecks.typed(restarted,"old-profile-bypass","look",1)),"v2_unknown_cannot_bypass_with_v1");
        rejects(()->restarted.submit(request(restarted,"new-owner-bypass","look",1,"55555555-5555-4555-8555-555555555555")),"v2_unknown_cannot_bypass_owner");
    }
    static void typedPlanRoundtrip()throws Exception{
        Path file=Files.createTempDirectory("interaction-v2-allkind-plan-").resolve("journal");
        List<RecoveryShortInputLedger.Request> requests=new ArrayList<>();List<JsonObject> statuses=new ArrayList<>();
        try(var store=new RecoveryShortInputLedger.FileStore(file)){
            var l=new RecoveryShortInputLedger(store,()->100);RecoveryInteractionChecks.setLedger(l);
            for(String kind:List.of("move","look","select_hotbar","break_block")){
                var r=request(l,"plan-roundtrip-"+kind,kind,kind.equals("break_block")?32:1,RecoveryShortInputChecks.OWNER);requests.add(r);
                var e=l.submit(r);l.rejectQueued(e,"offline_plan_roundtrip");statuses.add(NativeRecoveryShortInput.describe(e));
            }
        }
        try(var store=new RecoveryShortInputLedger.FileStore(file)){
            var l=new RecoveryShortInputLedger(store,()->200,true);RecoveryInteractionChecks.setLedger(l);
            for(int i=0;i<requests.size();i++){
                var r=requests.get(i);var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());
                check(e.request.equals(r)&&e.request.digest().equals(r.digest()),"each_kind_plan_binary_roundtrip");
                check(NativeRecoveryShortInput.status(query(r),V2).equals(statuses.get(i)),"historical_v2_status_without_current_plan");
                var stop=query(r);stop.addProperty("schema_version",1);stop.addProperty("profile",V2);
                check(NativeRecoveryShortInput.stop(stop,V2).equals(statuses.get(i)),"historical_v2_stop_without_current_plan");
            }
        }
    }
    static JsonObject query(RecoveryShortInputLedger.Request r){JsonObject j=new JsonObject();j.addProperty("id",r.id());j.addProperty("session",r.session());j.addProperty("owner_id",r.ownerId());j.addProperty("owner_generation",r.generation());return j;}
    static void history94(Path fixtures,Path out)throws Exception{
        byte[] original=Files.readAllBytes(fixtures.resolve("native-94-entry-journal.bin"));Path temp=Files.createTempDirectory("interaction-v2-94-").resolve("journal");Files.write(temp,original);
        JsonObject actions=JsonParser.parseString(Files.readString(fixtures.resolve("public-ledger.json"))).getAsJsonObject().getAsJsonObject("actions");
        List<RecoveryShortInputLedger.Entry> old;JsonArray snapshots=new JsonArray();RecoveryShortInputLedger.Request added;
        try(var store=new RecoveryShortInputLedger.FileStore(temp)){
            old=store.read();check(old.size()==94,"real94_fixture_count");var l=new RecoveryShortInputLedger(store,()->100,true);RecoveryInteractionChecks.setLedger(l);
            check(!l.locked()&&l.nextGeneration()==95&&l.owner().equals(old.getFirst().request.ownerId()),"real94_owner_generation_continuity");
            for(var originalEntry:old){var r=originalEntry.request;var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());JsonObject status=NativeRecoveryShortInput.describe(e);
                check(status.equals(actions.getAsJsonObject(r.id()).getAsJsonObject("terminal_native")),"each_of94_terminal_exact_original_receipt");
                check(l.submit(r)==e,"each_of94_duplicate_same_entry_no_write");check(NativeRecoveryShortInput.status(query(r),r.profile()).equals(status),"each_of94_oldroot_status");
                var stop=query(r);stop.addProperty("schema_version",1);stop.addProperty("profile",r.profile());check(NativeRecoveryShortInput.stop(stop,r.profile()).equals(status),"each_of94_oldroot_exact_stop");
                rejects(()->NativeRecoveryShortInput.status(query(r),V2),"old_history_not_relabelled_as_v2");snapshots.add(status);
            }
            added=request(l,"88888888-8888-4888-8888-000000000095","break_block",32,l.owner());var a=l.submit(added);l.rejectQueued(a,"offline_known_zero");
            check(store.read().size()==95,"same_rsi2_appends_one_v2");
        }
        // The frozen v1 reader must reject a future v2 record, not reinterpret it as v1.
        Path oldClasses=fixtures.toAbsolutePath().getParent().getParent().getParent().resolve("mdc-recovery-interaction-test-r1/results/native/final-r5/classes-production");
        try(var loader=new java.net.URLClassLoader(new java.net.URL[]{oldClasses.toUri().toURL()},ClassLoader.getPlatformClassLoader())){
            Class<?> type=Class.forName("io.github.campione01.mineclientbridge.RecoveryShortInputLedger$FileStore",true,loader);
            var constructor=type.getDeclaredConstructor(Path.class);constructor.setAccessible(true);Object oldStore=constructor.newInstance(temp);
            var read=type.getDeclaredMethod("read");var close=type.getDeclaredMethod("close");read.setAccessible(true);close.setAccessible(true);
            try{read.invoke(oldStore);throw new AssertionError("frozen_v1_reader_accepted_v2");}
            catch(java.lang.reflect.InvocationTargetException expected){check(expected.getCause() instanceof java.io.IOException&&expected.getCause().getMessage().equals("ledger_profile"),"actual_frozen_v1_reader_fail_closed_on_v2");}
            finally{close.invoke(oldStore);}
        }
        try(var store=new RecoveryShortInputLedger.FileStore(temp)){
            var l=new RecoveryShortInputLedger(store,()->200,true);RecoveryInteractionChecks.setLedger(l);check(!l.locked()&&l.nextGeneration()==96,"mixed_history_restart_ready");
            for(int i=0;i<94;i++){var r=old.get(i).request;var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());check(e.request.equals(r)&&e.request.digest().equals(r.digest())&&NativeRecoveryShortInput.describe(e).equals(snapshots.get(i)),"every_original94_request_digest_terminal_preserved_after_rewrite");}
            var a=l.lookup(added.id(),added.session(),added.ownerId(),added.generation());check(a.request.equals(added)&&a.request.digest().equals(added.digest()),"v2_same_layout_roundtrip");
        }
        JsonObject wrapped=new JsonObject();wrapped.add("statuses",snapshots);Files.write(out.resolve("legacy94-preserved-statuses.json"),RecoveryShortInputCodec.encode(wrapped));
        check(Arrays.equals(original,Files.readAllBytes(fixtures.resolve("native-94-entry-journal.bin"))),"fixture_original_bytes_untouched");
        Path pending=Files.createTempDirectory("interaction-v2-oldpending-").resolve("journal");Files.write(pending,original);
        try(var store=new RecoveryShortInputLedger.FileStore(pending)){var entries=store.read();entries.getLast().state="ACTIVE";entries.getLast().invalidated=false;store.write(entries);var l=new RecoveryShortInputLedger(store,()->1,true);check(l.locked(),"old94_unfinished_blocks_v2");rejects(()->l.submit(request(l,"no_reset","look",1,l.owner())),"old_unknown_no_v2_reset");}
        try(var store=new RecoveryShortInputLedger.FileStore(pending)){check(new RecoveryShortInputLedger(store,()->2,true).locked(),"old_unknown_still_persistent");}
    }
    static void wire(Path out)throws Exception{
        Files.createDirectories(out);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);RecoveryInteractionChecks.setLedger(l);int i=0;
        for(String kind:List.of("move","look","select_hotbar","break_block")){
            var body=json(request(l,String.format("99999999-9999-4999-8999-%012d",++i),kind,kind.equals("break_block")?32:1,RecoveryShortInputChecks.OWNER));var r=parse(body);var e=l.submit(r);
            Files.write(out.resolve(kind+"-request.json"),RecoveryShortInputCodec.encode(body));Files.write(out.resolve(kind+"-queued.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));
            if(kind.equals("break_block")){check(l.claimCall(e,1,true),"wire_native_claim");l.completeCall(e);e.gameplay="target_unchanged";}else check(l.sample(e,1,true,()->{}),"wire_sample");
            l.stop(e,"offline_fixture_stop");l.release(e,true,()->{},true,"offline_fixture_release");Files.write(out.resolve(kind+"-settled.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));
            check(NativeRecoveryShortInput.describe(e).get("profile").getAsString().equals(V2),"actual_status_stored_v2_profile");
        }
        Files.write(out.resolve("observe-no-world.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describeNoWorld(false,true,V2)));
        var zero=l.submit(request(l,"99999999-9999-4999-8999-000000000005","look",1,l.owner()));l.rejectQueued(zero,"observation_stale_or_moved");Files.write(out.resolve("zero-request.json"),RecoveryShortInputCodec.encode(json(zero.request)));Files.write(out.resolve("zero-settled.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(zero)));
        var active=l.submit(request(l,"99999999-9999-4999-8999-000000000006","break_block",32,l.owner()));check(l.claimCall(active,99,true),"wire_entered");l.stop(active,"explicit_stop");Files.write(out.resolve("entered-request.json"),RecoveryShortInputCodec.encode(json(active.request)));Files.write(out.resolve("entered-stop.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(active)));l.failedCall(active);l.release(active,true,()->{},true,"offline_unknown_release");Files.write(out.resolve("unknown-released.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(active)));
        JsonObject v1=RecoveryInteraction.describeHotbarStack(2,"minecraft:stone_pickaxe",1,106,131,"c".repeat(64),false),v2=RecoveryInteraction.describeHotbarStack(2,"minecraft:stone_pickaxe",1,106,131,"c".repeat(64),true);
        check(!v1.has("max_damage")&&v2.get("max_damage").getAsInt()==131,"production_hotbar_shape_versioned");check(v2.get("max_damage").getAsInt()-v2.get("damage").getAsInt()==25,"actual_remaining_damage_not_hardcoded_window");
        Files.write(out.resolve("hotbar-v1-synthetic-input.json"),RecoveryShortInputCodec.encode(v1));Files.write(out.resolve("hotbar-v2-synthetic-input.json"),RecoveryShortInputCodec.encode(v2));
        var air=RecoveryInteraction.describeHotbarStack(0,"minecraft:air",0,0,0,"d".repeat(64),true);check(air.get("max_damage").getAsInt()==0,"air_max_damage_zero");Files.write(out.resolve("hotbar-air-synthetic-input.json"),RecoveryShortInputCodec.encode(air));
    }
}
