package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

/** Pure exact serializers shared by genuine readers and finite cross-language fixtures. */
final class ObservationClockWire {
    static boolean selected(String query) {
        if(query==null || query.isEmpty())return false;
        boolean found=false;
        for(String part:query.split("&",-1)) {
            String[] pair=part.split("=",2);
            String key=URLDecoder.decode(pair[0],StandardCharsets.UTF_8);
            if(!key.equals("observation_clock"))continue;
            if(found || pair.length!=2 || !URLDecoder.decode(pair[1],StandardCharsets.UTF_8).equals(ObservationClientClock.CONTRACT))
                throw new IllegalArgumentException("invalid_observation_clock");
            found=true;
        }
        return found;
    }
    static JsonObject snapshot(JsonObject bundle,ObservationClientClock.Stamp before,ObservationClientClock.Stamp after) {
        if(before==null || !before.sameTurn(after))throw new ObservationClientClock.Unavailable("context_changed");
        bundle.addProperty("capability_snapshot_schema_version",2);
        bundle.addProperty("observation_clock_profile","read_only");bundle.add("observation_clock",before.json());
        for(String key:new String[]{"status","action","state","screen"})bundle.getAsJsonObject(key).add("observation_clock",before.json());
        return bundle;
    }
    static JsonObject page(JsonObject original,ObservationClientClock.Stamp source,ObservationClientClock.Stamp response) {
        if(source==null || !source.sameDomain(response) || response.count()<source.count())throw new ObservationClientClock.Unavailable("context_changed");
        original.addProperty("terrain_schema_version",2);original.addProperty("observation_clock_profile","read_only");
        original.add("source_clock",source.json());original.add("response_clock",response.json());return original;
    }
    private ObservationClockWire() { }
}
