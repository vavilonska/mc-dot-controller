package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Full-production-classpath refusal/HTTP encoder check; never loads or starts a game. */
public final class BeeDiagnosticWireProducer {
 public static void main(String[] args)throws Exception{
  Path source=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectory(out);int cases=0;
  try(var files=Files.list(source)){
   for(Path input:files.filter(p->p.getFileName().toString().startsWith("bee-diagnostic-")&&p.toString().endsWith(".json")).sorted().toList()){
    String original=Files.readString(input);var response=JsonParser.parseString(original).getAsJsonObject();
    var error=new ClientActionRequest.Rejected(409,response.get("error").getAsString(),null,null,response.getAsJsonObject("route_entity_rejection"));
    String encoded=BridgeJson.toJson(error.response());if(!original.equals(encoded))throw new AssertionError("Original refusal bytes changed: "+input);
    Files.writeString(out.resolve(input.getFileName()),encoded,StandardOpenOption.CREATE_NEW);cases++;
   }
  }
  var report=new JsonObject();report.addProperty("cases",cases);report.addProperty("status","passed");report.addProperty("scope","Exact original engine-produced refusal bytes re-encoded with full production ClientActionRequest.Rejected and BridgeJson; no game or world execution");
  Files.writeString(out.resolve("diagnostic-wire-result.json"),report.toString(),StandardOpenOption.CREATE_NEW);System.out.println("PASS original bee diagnostic production HTTP bytes="+cases);
 }
}
