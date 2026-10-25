package io.github.campione01.mineclientbridge;
import com.google.gson.*;
public final class AdmissionBoundaryChecks {
 static int checks;
 static void check(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
 static JsonObject request(){return JsonParser.parseString("{\"action\":\"follow_path\",\"action_id\":\"original\",\"expected_action_session\":\"session\"}").getAsJsonObject();}
 static JsonObject response(NativeAdmission.Stage stage,boolean nested)throws Exception{
  var b=request();var r=BridgeServer.ActionResponses.result(()->NativeAdmission.run(b,false,"session",()->{
   NativeAdmission.ordinaryStartEntered();NativeAdmission.mark(stage);
   if(nested){try{NativeAdmission.run(b,false,"session",()->new JsonObject());}catch(ClientActionRequest.Rejected swallowed){}}
   NativeAdmission.mark(NativeAdmission.Stage.VALIDATION);
   throw new ClientActionRequest.Rejected(409,"navigation_not_settled");
  }),true);
  check(r.status()==409);return JsonParser.parseString(BridgeJson.toJson(r.body())).getAsJsonObject().getAsJsonObject("native_admission");
 }
 public static void main(String[]args)throws Exception{
  for(var stage:NativeAdmission.Stage.values()){
   var p=response(stage,false);
   check(p.get("boundary_schema_version").getAsInt()==2);check(p.get("ordinary_start_entered").getAsBoolean());
   check(p.get("input_transfer_entered").getAsBoolean()==(stage.ordinal()>=NativeAdmission.Stage.INPUT_TRANSFER.ordinal()));
   check(p.get("registration_entered").getAsBoolean()==(stage==NativeAdmission.Stage.REGISTERED));
   check(!p.get("reentry_observed").getAsBoolean());
   check(p.get("effects_none_proven").getAsBoolean()==(stage==NativeAdmission.Stage.VALIDATION));
   check(p.get("request_payload_sha256").getAsString().equals(ScopedNativePreflight.digest(request())));
   check(p.get("action_id").getAsString().equals("original"));
  }
  var p=response(NativeAdmission.Stage.HOOKS_POSSIBLE,true);check(p.get("reentry_observed").getAsBoolean());check(!p.get("effects_none_proven").getAsBoolean());
  var fresh=response(NativeAdmission.Stage.HOOKS_POSSIBLE,false);check(!fresh.get("reentry_observed").getAsBoolean());
  try{BridgeServer.ActionResponses.result(()->NativeAdmission.run(request(),false,"session",()->{NativeAdmission.ordinaryStartEntered();throw new IllegalStateException("unknown");}),true);throw new AssertionError("unexpected receipt");}catch(IllegalStateException expected){check(expected.getMessage().equals("unknown"));}
  var scoped=new NativeAdmission(request(),true,"session").proof("scoped");check(!scoped.get("ordinary_start_entered").getAsBoolean());
  System.out.println("PASS "+checks+" boundary/monotonic-stage/nested-swallowed-reentry/real-HTTP-wrapper-serialization assertions; no game runtime");
 }
}
