package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;

/** Pure production policy/proof/HTTP serialization fixture; no client or world constructed. */
public final class NativeOutcomeWire {
    static int checks;
    static void check(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    static void placement(){
        var verification=new PlacementEffectVerification();
        for(int tick=1;tick<32;tick++)check(verification.observe(tick,false,false,false)==PlacementEffectVerification.Decision.WAIT);
        for(int tick=32;tick<36;tick++)check(verification.observe(tick,true,true,true)==PlacementEffectVerification.Decision.WAIT);
        check(verification.observe(36,true,true,true)==PlacementEffectVerification.Decision.OBSERVED);
        // FAIL's later readback can prove effects, but cannot create another interaction.
        var absent=new PlacementEffectVerification();
        for(int tick=1;tick<40;tick++)check(absent.observe(tick,false,true,true)==PlacementEffectVerification.Decision.WAIT);
        check(absent.observe(40,false,true,true)==PlacementEffectVerification.Decision.UNKNOWN);
        var noConsumption=new PlacementEffectVerification();
        for(int tick=1;tick<=40;tick++)check(noConsumption.observe(tick,true,false,true)!=(PlacementEffectVerification.Decision.OBSERVED));
        var repeated=new PlacementEffectVerification();
        for(int i=0;i<20;i++)check(repeated.observe(1,true,true,true)==PlacementEffectVerification.Decision.WAIT);
        check(repeated.stableTicks()==1);
        repeated.observe(2,true,true,true);repeated.observe(3,true,true,true);repeated.observe(4,true,true,true);
        check(repeated.observe(4,false,true,true)==PlacementEffectVerification.Decision.WAIT);
        check(repeated.stableTicks()==0);
        check(repeated.observe(3,true,true,true)==PlacementEffectVerification.Decision.UNKNOWN);
        check(new PlacementEffectVerification().observe(41,true,true,true)==PlacementEffectVerification.Decision.UNKNOWN);
    }
    public static void main(String[] args)throws Exception {
        Object owner=new Object(),player=new Object(),level=new Object(),mode=new Object(),menu=new Object();
        PlacementOwnerFence boundary=new PlacementOwnerFence(owner,player,level,mode,menu,null,"session","world");
        if(!boundary.same(owner,player,level,mode,menu,null,"session","world"))throw new AssertionError("same_owner");
        for(int replace=0;replace<8;replace++){
            Object other=new Object();
            if(boundary.same(replace==0?other:owner,replace==1?other:player,replace==2?other:level,
                replace==3?other:mode,replace==4?other:menu,replace==5?other:null,
                replace==6?"changed":"session",replace==7?"changed":"world"))throw new AssertionError("late_callback_owner_changed");
        }

        Path out=Path.of(args[0]);Files.createDirectories(out);placement();
        JsonObject request=JsonParser.parseString("""
            {"preflight":{"version":"scoped-native-preflight/1","profile":"placement-local-observed-v1","owner_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","owner_generation":1,"job_id":"job-one","defense_epoch":7},"intent":{"action":"place_block","action_id":"action-one","expected_action_session":"session-one"}}
            """).getAsJsonObject();
        Files.writeString(out.resolve("request.json"),request.toString());
        for(var stage:NativeAdmission.Stage.values()){
            var response=BridgeServer.ActionResponses.result(()->NativeAdmission.run(request,true,"session-one",()->{
                NativeAdmission.mark(stage);
                // A marker can never move backwards and turn a hook-stage failure into a no-effect proof.
                NativeAdmission.mark(NativeAdmission.Stage.VALIDATION);
                throw new ClientActionRequest.Rejected(409,"unsupported_scoped_version");
            }),true);
            check(response.status()==409);
            JsonObject proof=response.body().getAsJsonObject("native_admission");
            check(proof.get("effects_none_proven").getAsBoolean()==(stage==NativeAdmission.Stage.VALIDATION));
            check(proof.get("request_payload_sha256").getAsString().equals(ScopedNativePreflight.digest(request)));
            Files.writeString(out.resolve(stage.name().toLowerCase()+".json"),BridgeJson.toJson(response.body()));
        }
        var admission=new NativeAdmission(request,true,"session-one");
        JsonObject first=admission.proof("original");
        admission.advance(NativeAdmission.Stage.REGISTERED);
        check(first.get("effects_none_proven").getAsBoolean());
        first.getAsJsonObject("scope").addProperty("owner_id","changed");
        check(admission.proof("later").getAsJsonObject("scope").get("owner_id").getAsString().equals("a".repeat(32)));
        var entity=NativeEntityDiagnostics.unsupported(new Object(),"mining-local-observed-v2");
        var response=BridgeServer.ActionResponses.result(()->NativeAdmission.run(request,true,"session-one",()->{
            NativeAdmission.mark(NativeAdmission.Stage.HOOKS_POSSIBLE);throw entity;
        }),true);
        check(response.body().getAsJsonObject("native_entity_rejection").get("entity_class").getAsString().equals("java.lang.Object"));
        check(!response.body().getAsJsonObject("native_admission").get("effects_none_proven").getAsBoolean());
        Files.writeString(out.resolve("entity.json"),BridgeJson.toJson(response.body()));
        var reentry=BridgeServer.ActionResponses.result(()->NativeAdmission.run(request,true,"session-one",()->
            NativeAdmission.run(request,true,"session-one",()->new JsonObject())),true);
        check(!reentry.body().getAsJsonObject("native_admission").get("effects_none_proven").getAsBoolean());
        System.out.println("PASS "+checks+" assertions; production pure policy, admission and HTTP serialization only; no game execution");
    }
}
