package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.io.*;
/** Canonical offline acceptance seam: production receipt/parser, ActionResponses, BridgeJson bytes. */
public final class FallRescueAdjudicationCodec {
 public static void main(String[] args)throws Exception{
  var reader=new BufferedReader(new InputStreamReader(System.in));String line;
  while((line=reader.readLine())!=null){
   var input=JsonParser.parseString(line).getAsJsonObject();var payload=input.getAsJsonObject("payload").deepCopy();
   var response=BridgeServer.ActionResponses.result(()->{
    if(input.has("reject"))throw new ClientActionRequest.Rejected(409,"fall_adjudication_exact_quarantine_required");
    if(input.has("native_request")){var r=FallRescueAdjudication.parse(input.getAsJsonObject("native_request"));payload.add("receipt",FallRescueAdjudication.receipt(r,r.revision()+1));}
    if(input.has("not_found"))payload.add("receipt",new FallRescueAdjudication.Ledger().read(input.get("not_found").getAsString()));
    return payload;
   },false);
   System.out.println(response.status()+"\t"+BridgeJson.toJson(response.body()));System.out.flush();
  }
 }
}
