package io.github.campione01.mineclientbridge;

import java.util.UUID;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class IntegratedServerIdentityTest {
    @Test void oneServerSurvivesDimensionChangesButDifferentSaveAndDisconnectDoNot() {
        IntegratedServerIdentity.clear();Object server=new Object();
        String before=IntegratedServerIdentity.current(server,true);
        assertEquals(before,UUID.fromString(before).toString());
        String firstLevel=WorldGeneration.current(new Object());
        String nextLevel=WorldGeneration.current(new Object());
        assertNotEquals(firstLevel,nextLevel);assertEquals(before,IntegratedServerIdentity.current(server,true));
        assertNotEquals(before,IntegratedServerIdentity.current(new Object(),true));
        before=IntegratedServerIdentity.current(server,true);IntegratedServerIdentity.clear();
        assertNotEquals(before,IntegratedServerIdentity.current(server,true));
    }
    @Test void nonprivateAndDisconnectedObservationsExposeNoServerIdentity() throws Exception {
        Object server=new Object();String before=IntegratedServerIdentity.current(server,true);
        assertNull(IntegratedServerIdentity.current(server,false));
        assertNotEquals(before,IntegratedServerIdentity.current(server,true));
        before=IntegratedServerIdentity.current(server,true);assertNull(IntegratedServerIdentity.current(null,true));
        assertNotEquals(before,IntegratedServerIdentity.current(server,true));
        var world=new JsonObject();world.addProperty("integrated_server_instance",IntegratedServerIdentity.current(server,false));
        assertFalse(JsonParser.parseString(BridgeJson.toJson(world)).getAsJsonObject().has("integrated_server_instance"));
    }
}
