package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Actual production HTTP response wrapper over production episode-model fixtures; no game launch. */
public final class FallRescueHttpFixtures {
 public static void main(String[] args)throws Exception{
  var rows=JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonArray();var wrapped=new JsonArray();
  for(var row:rows){var response=BridgeServer.ActionResponses.result(()->row.getAsJsonObject().deepCopy(),false);
   if(response.status()!=200)throw new AssertionError();wrapped.add(JsonParser.parseString(BridgeJson.toJson(response.body())));}
  Files.writeString(Path.of(args[1]),wrapped.toString());System.out.println("actual Java HTTP wrapper fixtures="+wrapped.size());
 }
}
