package io.github.campione01.mineclientbridge;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
/** Reads cross-language producer cases and invokes the actual production closed intent validators. */
public final class TypedPortalIntentChecks {
    public static void main(String[] args)throws Exception{int passed=0;for(var element:JsonParser.parseReader(Files.newBufferedReader(Path.of(args[0]))).getAsJsonArray()){
        var c=element.getAsJsonObject();boolean valid=true;try{
            if(c.get("type").getAsString().equals("item"))ScopedItemInteractionIntent.validate(c.getAsJsonObject("intent"));
            else ScopedPortalEntryIntent.validate(c.getAsJsonObject("intent"));
            ClientActionRequest.parse(c.getAsJsonObject("intent"));
        }catch(RuntimeException denied){valid=false;}
        if(valid!=c.get("valid").getAsBoolean())throw new AssertionError(c.get("name").getAsString()+" expected "+c.get("valid")+" got "+valid);passed++;
    }System.out.println("typed portal production intent checks: "+passed+" passed");}
}
