package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Exact existing production rejection codec. Does not initialize a game or server. */
public final class FallRescueRenewRefusalFixtures {
 public static void main(String[] args)throws Exception {
  var rows=new JsonArray();
  for(var entry:new String[][]{{"refused","409","fall_rescue_not_armed"},{"wrong_status","500","fall_rescue_not_armed"},{"wrong_reason","409","fall_rescue_owner_changed"}}){
   var response=BridgeServer.ActionResponses.result(()->{throw new ClientActionRequest.Rejected(Integer.parseInt(entry[1]),entry[2]);},false);
   var row=new JsonObject();row.addProperty("name",entry[0]);row.addProperty("http_status",response.status());
   row.addProperty("body",BridgeJson.toJson(response.body()));rows.add(row);
  }
  Files.writeString(Path.of(args[0]),rows.toString());System.out.println("actual ActionResponses + BridgeJson refusal fixtures="+rows.size());
 }
}
