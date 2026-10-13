package io.github.campione01.mineclientbridge;
import java.util.ArrayList;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class BoatInputReleaseTest {
 @Test void cancelReleasesBothOwnedLayersWithoutBraking(){var calls=new ArrayList<String>();BoatInputRelease.clear((l,r,u,d)->calls.add("boat:"+l+r+u+d),(l,r,u,d)->calls.add("player:"+l+r+u+d));assertEquals(java.util.List.of("boat:falsefalsefalsefalse","player:falsefalsefalsefalse"),calls);}
 @Test void failureInBoatLayerStillAttemptsPlayerLayer(){boolean[] player={false};assertThrows(IllegalStateException.class,()->BoatInputRelease.clear((l,r,u,d)->{throw new IllegalStateException();},(l,r,u,d)->{player[0]=true;assertFalse(l||r||u||d);}));assertTrue(player[0]);}
 @Test void failedReleaseCannotPublishSuccessfulAction(){var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(BoatDriveRequestTest.body()));registry.finishAfterCleanup("succeeded","boat_settled_at_endpoint",false);assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);assertFalse(entry.result.get("input_release_confirmed").getAsBoolean());}
 @Test void successfulCancelIsTerminalAndDuplicateNeverReleasesANewerOwner(){var registry=new ActionRegistry();var request=ClientActionRequest.parse(BoatDriveRequestTest.body());var old=registry.begin(request);registry.finishAfterCleanup("cancelled","deadline_or_stop",true);var fresh=BoatDriveRequestTest.body();fresh.addProperty("action_id","boat-new");var active=registry.begin(ClientActionRequest.parse(fresh));assertSame(old,registry.existing(request));assertSame(active,registry.active());assertTrue(old.result.get("input_release_confirmed").getAsBoolean());}
}
