package io.github.campione01.mineclientbridge;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class SprintKeyStateTest {
    static class Key {
        boolean down, toggle;
        final List<Boolean> calls=new ArrayList<>();
        Key(boolean toggle) { this.toggle=toggle; }
        void setDown(boolean value) {
            calls.add(value);
            if (toggle) { if (value) down=!down; }
            else down=value;
        }
        void want(boolean desired) { SprintKeyState.set(()->down,this::setDown,desired); }
    }
    @Test void holdKeyHasOnePressOneReleaseAcrossManyTicks() {
        Key k=new Key(false);for(int i=0;i<20;i++)k.want(true);
        assertTrue(k.down);assertEquals(List.of(true),k.calls);
        k.want(false);k.want(false);assertFalse(k.down);assertEquals(List.of(true,false),k.calls);
    }
    @Test void toggleKeyNeverOscillatesAndAlwaysTurnsOffAtEnd() {
        Key k=new Key(true);for(int i=0;i<20;i++)k.want(true);
        assertTrue(k.down);assertEquals(List.of(true),k.calls);
        k.want(false);k.want(false);assertFalse(k.down);assertEquals(List.of(true,false,true),k.calls);
    }
    @Test void changingHoldToToggleBeforeReleaseStillClearsActualState() {
        Key k=new Key(false);k.want(true);k.toggle=true;k.want(false);assertFalse(k.down);
    }
    @Test void changingToggleToHoldBeforeReleaseStillClearsActualState() {
        Key k=new Key(true);k.want(true);k.toggle=false;k.want(false);assertFalse(k.down);
    }
    @Test void unsupportedSetterCannotPretendReleaseSucceeded() {
        assertThrows(IllegalStateException.class,()->SprintKeyState.set(()->true,ignored->{},false));
    }
    @Test void cleanupFailureCannotBeReportedAsPathSuccess() {
        ActionRegistry registry=new ActionRegistry();
        registry.begin(ClientActionRequest.parse(com.google.gson.JsonParser.parseString("{\"action_id\":\"a\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"y\":64,\"z\":1}]}").getAsJsonObject()));
        registry.finishAfterCleanup("succeeded","path_reached",false);
        var result=registry.status("a");
        assertEquals("failed",result.get("status").getAsString());
        assertEquals("input_release_unconfirmed",result.get("reason").getAsString());
        assertFalse(result.getAsJsonObject("result").get("input_release_confirmed").getAsBoolean());
        assertEquals("succeeded",result.getAsJsonObject("result").get("requested_terminal_status").getAsString());
    }
}
