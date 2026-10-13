package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class CoordinationStepGuardTest {
    static final ClientActionRequest.Point START=new ClientActionRequest.Point(.5,64,.5,false);
    static final ClientActionRequest.Point END=new ClientActionRequest.Point(1.5,64,.5,false);
    static FlatStepCorridor.Cell cell(int x,int y,int z) {
        boolean floor=y==63;
        return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,floor?"minecraft:stone":"minecraft:air",
                true,!floor,floor,"minecraft:empty",false);
    }
    static CoordinationStepPolicy.State state(int entities,boolean life,double x,float hp) {
        return new CoordinationStepPolicy.State(x,64,.5,0,true,true,life,false,.1,hp,.6,.6,1.8,entities);
    }
    static JsonObject request() {
        return JsonParser.parseString("""
        {"action_id":"one","action":"follow_path","timeout_ms":1000,"waypoints":[{"x":1.5,"y":64,"z":0.5}],
        "expected_origin":{"x":0.5,"y":64,"z":0.5},"expected_navigation_epoch":0,
        "expected_world_generation":"world","expected_player_uuid":"player","expected_action_session":"session",
        "coordination_step":{"schema_version":1,"source_tick":10,"source_nano":"-1234567890123456789"}}
        """).getAsJsonObject();
    }
    @Test void sourceNanoAgeAllowsNegativeClockButRejectsFutureAndExpired() {
        assertTrue(CoordinationStepPolicy.ageValid(-100,-200));
        assertTrue(CoordinationStepPolicy.ageValid(0,-800_000_000));
        assertFalse(CoordinationStepPolicy.ageValid(0,-800_000_001));
        assertFalse(CoordinationStepPolicy.ageValid(-200,-100));
    }
    @Test void optInExactScopeAndLegacyRemainSeparate() {
        assertEquals("follow_path",ClientActionRequest.parse(request()).action());
        var unknown=request(); unknown.addProperty("raw_key","forward");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(unknown));
        var sprint=request();sprint.addProperty("sprint",true);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(sprint));
        var timeout=request();timeout.addProperty("timeout_ms",1001);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(timeout));
        var longer=request();longer.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("x",2.5);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(longer));
        var legacy=request();legacy.remove("coordination_step");legacy.addProperty("timeout_ms",15000);
        legacy.addProperty("legacy_extra","kept");assertEquals(15000,ClientActionRequest.parse(legacy).timeoutMs());
    }
    @Test void nativeNanoIsStrictStringAndOriginIsNumeric() {
        for (var text : new String[]{"1.5","NaN","9223372036854775808","+1"}) {
            var p=request();p.getAsJsonObject("coordination_step").addProperty("source_nano",text);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(p));
        }
        var number=request();number.getAsJsonObject("coordination_step").addProperty("source_nano",42);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(number));
        var string=request();string.getAsJsonObject("expected_origin").addProperty("x","0.5");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(string));
    }
    @Test void dynamicEntitiesDamageAndLifecycleRejectWithoutChangingOldActionPolicy() {
        assertNull(CoordinationStepPolicy.check(START,END,20,state(0,true,.5,20),CoordinationStepGuardTest::cell));
        assertEquals("coordination_step_entity_nearby",CoordinationStepPolicy.check(START,END,20,state(1,true,.5,20),CoordinationStepGuardTest::cell));
        assertEquals("coordination_step_motion_or_damage",CoordinationStepPolicy.check(START,END,20,state(0,true,.5,19),CoordinationStepGuardTest::cell));
        assertNull(CoordinationStepPolicy.check(START,END,5,state(0,true,.5,6),CoordinationStepGuardTest::cell));
        assertEquals("coordination_step_motion_or_damage",CoordinationStepPolicy.check(START,END,6,state(0,true,.5,5.5f),CoordinationStepGuardTest::cell));
        assertEquals("coordination_step_lifecycle",CoordinationStepPolicy.check(START,END,20,state(0,false,.5,20),CoordinationStepGuardTest::cell));
        assertEquals("coordination_step_left_corridor",CoordinationStepPolicy.check(START,END,20,state(0,true,1.7,20),CoordinationStepGuardTest::cell));
    }
    @Test void fullContinuousCorridorRejectsMissingSupportGrassUnknownAndFluid() {
        for (var bad : new FlatStepCorridor.Cell[]{
                new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNLOADED,"minecraft:air",true,true,false,"minecraft:empty",false),
                new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:short_grass",true,true,false,"minecraft:empty",false),
                new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",false,true,false,"minecraft:empty",false),
                new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:water",false)}) {
            assertNotNull(CoordinationStepPolicy.check(START,END,20,state(0,true,.5,20),(x,y,z)->x==1&&y==64?bad:cell(x,y,z)));
        }
        assertNotNull(CoordinationStepPolicy.check(START,END,20,state(0,true,.5,20),(x,y,z)->y==63&&x==1?cell(x,64,z):cell(x,y,z)));
    }
    @Test void failureAfterInputTransferCannotMasqueradeAsNoEffect409() {
        int[] releases={0};
        var changed=assertThrows(IllegalStateException.class,()->CoordinationStepPolicy.transfer(
                ()->releases[0]++,()->{throw new ClientActionRequest.Rejected(409,"source_expired");}));
        assertEquals(1,releases[0]);
        assertEquals("coordination_step_transfer_outcome_unknown",changed.getMessage());
        int[] newerOwner={7};
        assertThrows(IllegalStateException.class,()->CoordinationStepPolicy.transfer(
                ()->{releases[0]++;newerOwner[0]=8;},()->{throw new IllegalStateException("owner_changed");}));
        assertEquals(8,newerOwner[0]); // No cancellation or write to that newer owner.
    }
    @Test void bridgeJsonRetainsSignedNanoAndUnavailableEvidence() throws Exception {
        JsonObject root=new JsonObject();
        root.add("coordination_step",CoordinationStepGuard.sampleEvidence(10,Long.MIN_VALUE,"w","s","p",0,true));
        String encoded=BridgeJson.toJson(root);
        assertEquals(Long.toString(Long.MIN_VALUE),JsonParser.parseString(encoded).getAsJsonObject()
                     .getAsJsonObject("coordination_step").get("source_nano").getAsString());
        var unavailable=CoordinationStepGuard.sampleEvidence(11,-1,"w","s","p",1,false);
        root.add("coordination_step",unavailable);
        String denied=BridgeJson.toJson(root);
        assertFalse(JsonParser.parseString(denied).getAsJsonObject().getAsJsonObject("coordination_step").get("singleplayer").getAsBoolean());
        Path output=Path.of(System.getProperty("mineclientBridge.projectDir"),"build","validation","coordination-step-wire.json");
        Files.createDirectories(output.getParent());
        Files.writeString(output,"{\"success\":"+encoded+",\"unavailable\":"+denied+"}");
    }
}
