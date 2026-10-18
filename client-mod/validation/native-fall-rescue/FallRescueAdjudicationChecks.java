package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Production parser, immutable ledger and exact quarantine CAS; no game startup. */
public final class FallRescueAdjudicationChecks {
 static int n;static void ok(boolean b){n++;if(!b)throw new AssertionError("check "+n);}
 static void reject(Runnable r){n++;try{r.run();throw new AssertionError("accepted "+n);}catch(IllegalStateException|ClientActionRequest.Rejected expected){}}
 public static void main(String[] args)throws Exception{
  JsonObject body=new JsonObject();body.addProperty("adjudication_schema_version",1);body.addProperty("adjudication_id","adjudication-one");
  for(String key:new String[]{"arm_id","owner_id","episode_id","original_action_id","expected_action_session","expected_world_generation","expected_player_uuid"})body.addProperty(key,key);
  body.addProperty("episode_id","arm_id:1");body.addProperty("original_receipt_sha256","a".repeat(64));body.addProperty("expected_arbiter_revision",8);body.addProperty("acknowledgment",FallRescueAdjudication.ACK);
  var request=FallRescueAdjudication.parse(body);ok(request.revision()==8);
  for(String key:body.keySet()){var changed=body.deepCopy();changed.remove(key);reject(()->FallRescueAdjudication.parse(changed));}
  for(String key:body.keySet()){var changed=body.deepCopy();changed.add(key,JsonNull.INSTANCE);reject(()->FallRescueAdjudication.parse(changed));}
  for(String key:new String[]{"acknowledgment","original_receipt_sha256","adjudication_id","expected_arbiter_revision"}){var changed=body.deepCopy();changed.addProperty(key,"wrong value");reject(()->FallRescueAdjudication.parse(changed));}
  var unknown=body.deepCopy();unknown.addProperty("override",true);reject(()->FallRescueAdjudication.parse(unknown));
  var owner=new SingleInputArbiter();owner.quarantine("native_fall_rescue_original_action_quarantined");long revision=owner.revision();
  reject(()->owner.adjudicateOriginal(revision-1));ok(owner.quarantined());
  owner.adjudicateOriginal(revision);ok(!owner.blocked()&&owner.revision()==revision+1);reject(()->owner.adjudicateOriginal(revision));
  for(String reason:new String[]{"unknown","native_fall_rescue_input_release_unconfirmed","native_fall_rescue_unknown_outcome_quarantined"}){var a=new SingleInputArbiter();a.quarantine(reason);reject(()->a.adjudicateOriginal(a.revision()));ok(a.quarantined());}
  var reentry=new SingleInputArbiter();reentry.stopAndCleanup("native_fall_rescue_original_action_quarantined",()->reject(()->reentry.adjudicateOriginal(reentry.revision())));ok(reentry.quarantined());
  var ledger=new FallRescueAdjudication.Ledger();var proof=FallRescueAdjudication.receipt(request,9);ledger.commit(request.id(),proof);proof.addProperty("original_effects","known");
  ok(ledger.read(request.id()).get("original_effects").getAsString().equals("unknown"));var read=ledger.read(request.id());read.addProperty("no_auto_resume",false);ok(ledger.read(request.id()).get("no_auto_resume").getAsBoolean());reject(()->ledger.commit(request.id(),proof));
  for(int i=1;i<128;i++)ledger.commit("id"+i,proof);reject(()->ledger.commit("overflow",proof));ok(ledger.read("missing").get("status").getAsString().equals("not_found"));
  var result=BridgeServer.ActionResponses.result(()->FallRescueAdjudication.receipt(FallRescueAdjudication.parse(body),9),false);ok(result.status()==200);
  if(args.length>0){var fixture=new JsonObject();fixture.add("request",body);fixture.add("receipt",FallRescueAdjudication.receipt(request,9));fixture.add("http_wrapper_example",result.body());Files.writeString(Path.of(args[0]),BridgeJson.toJson(fixture));}
  System.out.println("PASS adjudication pure/parser/wire checks="+n+" game_started=false");
 }
}
