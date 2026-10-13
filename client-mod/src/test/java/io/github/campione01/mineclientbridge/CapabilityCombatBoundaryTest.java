package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Actual JSON encoder -> command parser -> the production ongoing native guard policy.
 * Entity observations are explicit synthetic samples here; genuine raw shell access has a separate loader test. */
class CapabilityCombatBoundaryTest {
    private static final String ID="00000000-0000-4000-8000-000000000012";
    private static final long NANO=1_000_000_000L;
    private static JsonObject base(String action) {
        var b=CapabilityGuardTest.request(action);b.remove("hotbar_slot");
        for(String field:List.of("expected_world_generation","expected_player_uuid","expected_action_session"))b.addProperty(field,ID);
        return b;
    }
    static JsonObject route(boolean guarded,boolean targeted) {
        var b=base("follow_path");b.add("waypoints",JsonParser.parseString("[{\"x\":1.5,\"y\":64,\"z\":0.5},{\"x\":2.5,\"y\":64,\"z\":0.5}]"));
        b.add("expected_origin",JsonParser.parseString("{\"x\":0.5,\"y\":64,\"z\":0.5}"));
        b.addProperty("expected_navigation_epoch",1);b.addProperty("capability_route",true);b.addProperty("min_health",12);
        if(guarded) {
            var scope=new JsonObject();scope.addProperty("schema_version",1);
            if(targeted) {scope.addProperty("target_entity_id",12);scope.addProperty("target_uuid",ID);scope.addProperty("target_type","minecraft:spider");}
            b.add(CapabilityEncounterPolicy.FIELD,scope);
        }
        return b;
    }
    static JsonObject combat(double reserve) {
        var b=base("combat_entity");b.addProperty("target_entity_id",12);b.addProperty("target_uuid",ID);
        b.addProperty("target_type","minecraft:zombie");b.addProperty("min_health",reserve);return b;
    }
    static JsonObject shulker() {
        var b=base("shoot_entity");b.addProperty("target_entity_id",12);b.addProperty("target_uuid",ID);
        b.addProperty("target_type","minecraft:shulker");b.addProperty("min_health",12);b.addProperty("draw_ticks",20);return b;
    }
    private static ClientActionRequest wire(JsonObject body) {
        try {return ClientActionRequest.parse(JsonParser.parseString(BridgeJson.toJson(body)).getAsJsonObject());}
        catch(java.io.IOException failure) {throw new AssertionError(failure);}
    }
    private static CapabilityEncounterPolicy.Observed entity(int id,String type,double x,boolean dangerous,boolean projectile) {
        return new CapabilityEncounterPolicy.Observed(id,"00000000-0000-4000-8000-"+String.format("%012d",id),type,
                new CapabilityEncounterPolicy.Point(x,64,.5),true,dangerous,projectile,false,false,false,false,false,0,null);
    }
    private static String check(ClientActionRequest r,List<CapabilityEncounterPolicy.Observed> rows,long tick,long nano) {
        return CapabilityEncounterPolicy.check(r,new CapabilityEncounterPolicy.Point(.5,64,.5),rows,tick,nano,tick,nano+1,true);
    }
    @Test void actualCombatCommandKeepsCallerReserveAcrossNativeHealthSamples() throws Exception {
        var parsed=wire(combat(18));var spec=BoundedCombatRequest.parse(parsed.original());
        assertEquals(18,spec.minHealth());var health=new CombatThreats.HealthGuard(spec.minHealth());
        assertFalse(health.sample(1,NANO,20).interrupted());
        assertEquals("caller_min_health",health.sample(2,NANO+50_000_000L,17).reason());
        assertTrue(health.sample(3,NANO+100_000_000L,20).interrupted(),"Recovery must not unlatch this action");
        var evidence=new JsonObject();CombatInitialEvidence.initialize(spec,evidence,20,20);
        var decoded=JsonParser.parseString(BridgeJson.toJson(evidence)).getAsJsonObject();
        assertEquals(18,decoded.get("effective_min_health").getAsDouble());
    }
    @Test void lowerCallerReserveCannotWeakenExistingNativeFloor() {
        var spec=BoundedCombatRequest.parse(wire(combat(10)).original());
        var health=new CombatThreats.HealthGuard(spec.minHealth());
        assertEquals(14,health.minimumHealth());assertEquals("low_health",health.sample(1,NANO,14).reason());
        var omitted=combat(18);omitted.remove("min_health");
        assertEquals(14,BoundedCombatRequest.parse(wire(omitted).original()).minHealth());
        for(String bad:List.of("null","true","\"18\"","7.9","20.1","1e999")) {
            var b=combat(18);b.add("min_health",JsonParser.parseString(bad));
            // Incoming command JSON retains explicit null; the response encoder intentionally omits unrelated nulls.
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(JsonParser.parseString(b.toString()).getAsJsonObject()),bad);
        }
    }
    @Test void targetHealthBoundaryAndShellClosureUseCurrentNotAdmissionValues() {
        var parsed=wire(shulker());assertEquals("shoot_entity",parsed.action());
        double minimum=CapabilityCombatSafety.minimum(parsed.original(),8);
        assertTrue(CapabilityCombatSafety.healthy(20,minimum));assertFalse(CapabilityCombatSafety.healthy(12,minimum));
        assertFalse(CapabilityCombatSafety.healthy(Double.NaN,minimum));
        assertTrue(CapabilityCombatSafety.shellOpen(100,1));
        assertFalse(CapabilityCombatSafety.shellOpen(0,1),"Closed synchronized shell must win over a stale open animation");
        assertFalse(CapabilityCombatSafety.shellOpen(100,0),"Raw open command must not fabricate an opened animation");
        for(double invalid:new double[]{Double.NaN,Double.POSITIVE_INFINITY,-.1,1.1})assertFalse(CapabilityCombatSafety.shellOpen(100,invalid));
        assertFalse(CapabilityCombatSafety.shellOpen(-1,1));assertFalse(CapabilityCombatSafety.shellOpen(101,1));
    }
    @Test void speciesFloorsAndAttackSpeciesRemainUnexpanded() {
        for(String type:List.of("minecraft:enderman","minecraft:creeper","minecraft:cave_spider","minecraft:blaze")) {
            var b=shulker();b.addProperty("target_type",type);b.addProperty("min_health",10);
            if(type.equals("minecraft:enderman")){b.addProperty("action","attack_entity");b.remove("draw_ticks");b.addProperty("enderman_shelter_required",true);}
            if(type.equals("minecraft:creeper"))b.addProperty("creeper_safety_required",true);
            if(type.equals("minecraft:cave_spider"))b.addProperty("poison_guard_required",true);
            if(type.equals("minecraft:blaze"))b.addProperty("fire_resistance_required",true);
            assertThrows(ClientActionRequest.Rejected.class,()->wire(b),type);
            b.addProperty("min_health",12);assertDoesNotThrow(()->wire(b),type);
        }
        for(String type:List.of("minecraft:drowned","minecraft:vex","minecraft:warden","minecraft:breeze","minecraft:bee","minecraft:cow","minecraft:goat","minecraft:rabbit","minecraft:pufferfish")) {
            var b=shulker();b.addProperty("target_type",type);assertThrows(ClientActionRequest.Rejected.class,()->wire(b),type);
        }
    }
    @Test void realRouteCommandRejectsOmittedKnownThreatsAndNewNativeThreatBetweenCallbacks() {
        var request=wire(route(true,false));
        assertNull(check(request,List.of(),1,NANO));
        for(String omitted:List.of("minecraft:drowned","minecraft:vex","minecraft:warden","minecraft:breeze","minecraft:shulker","minecraft:goat","minecraft:rabbit","minecraft:pufferfish"))
            assertEquals("encounter_route_non_target_threat",check(request,List.of(entity(20,omitted,5,false,false)),2,NANO+50_000_000L),omitted);
        assertEquals("encounter_route_non_target_threat",check(request,List.of(entity(20,"example:new_enemy",5,true,false)),2,NANO+50_000_000L));
        assertEquals("encounter_route_projectile_near",check(request,List.of(entity(20,"minecraft:breeze_wind_charge",5,false,false)),2,NANO));
        assertEquals("encounter_route_projectile_near",check(request,List.of(entity(20,"example:new_projectile",5,false,true)),2,NANO));
    }
    @Test void fullRouteCorridorIsCheckedNotOnlyPlayerOrEndpoints() {
        var request=wire(route(true,false));
        // More than eight away from the player, but within eight of the next route segment.
        assertEquals("encounter_route_non_target_threat",check(request,List.of(entity(20,"minecraft:drowned",9,false,false)),1,NANO));
        assertNull(check(request,List.of(entity(20,"minecraft:drowned",10.5,false,false)),1,NANO));
    }
    @Test void exactRouteTargetNeverExemptsAnotherIdentityOrUnsupportedSpecies() {
        var request=wire(route(true,true));var target=entity(12,"minecraft:spider",3,true,false);
        assertNull(check(request,List.of(target),1,NANO));
        assertEquals("encounter_route_target_missing",check(request,List.of(),1,NANO));
        assertEquals("encounter_route_target_changed",check(request,List.of(entity(12,"minecraft:drowned",3,true,false)),1,NANO));
        assertEquals("encounter_route_non_target_threat",check(request,List.of(target,entity(13,"minecraft:spider",3,true,false)),1,NANO));
        var unsupported=route(true,true);unsupported.getAsJsonObject(CapabilityEncounterPolicy.FIELD).addProperty("target_type","minecraft:drowned");
        assertThrows(ClientActionRequest.Rejected.class,()->wire(unsupported));
    }
    @Test void currentBlazeShieldRoutePreservesTheExistingThirtyTwoBlockIsolationWindow() {
        var body=route(true,true);body.getAsJsonObject(CapabilityEncounterPolicy.FIELD).addProperty("target_type","minecraft:blaze");
        var request=wire(body);
        var shield=new CapabilityEncounterPolicy.Observed(12,ID,"minecraft:blaze",new CapabilityEncounterPolicy.Point(20,64,.5),
                true,true,false,false,false,false,false,true,16,null);
        var resistant=new CapabilityEncounterPolicy.Observed(12,ID,"minecraft:blaze",new CapabilityEncounterPolicy.Point(20,64,.5),
                true,true,false,false,false,false,false,false,12,null);
        var other=entity(20,"minecraft:goat",25,false,false);
        var fireball=entity(21,"minecraft:small_fireball",30,false,true);
        assertNull(check(request,List.of(shield),1,NANO));
        assertNull(check(request,List.of(resistant,other,fireball),1,NANO));
        assertEquals("encounter_route_blaze_isolation_guard",check(request,List.of(shield,other),2,NANO));
        assertEquals("encounter_route_blaze_fireball_guard",check(request,List.of(shield,fireball),2,NANO));
    }
    @Test void ordinaryNoncombatAndPassiveMovementRemainUnchanged() {
        var ordinary=wire(route(false,false));
        assertNull(check(ordinary,List.of(entity(20,"minecraft:warden",1,true,false)),1,NANO));
        assertNull(CapabilityEncounterPolicy.check(ordinary,null,null,0,0,99,NANO,false));
        for(String type:List.of("minecraft:goat","minecraft:rabbit","minecraft:pufferfish")) {
            assertNull(check(ordinary,List.of(entity(20,type,1,false,false)),1,NANO));
            assertFalse(CombatThreats.observableThreat(type),"Legacy broad taxonomy stays unchanged");
        }
        var guarded=wire(route(true,false));
        for(String type:List.of("minecraft:cow","minecraft:chicken","minecraft:pig","minecraft:sheep","minecraft:bat"))
            assertNull(check(guarded,List.of(entity(20,type,1,false,false)),1,NANO),type);
    }
    @Test void optInWireRejectsPartialOrBypassScopesAndStaleIncompleteNativeSamples() {
        for(String field:List.of("target_entity_id","target_uuid","target_type")) {
            var b=route(true,true);b.getAsJsonObject(CapabilityEncounterPolicy.FIELD).remove(field);
            assertThrows(ClientActionRequest.Rejected.class,()->wire(b));
        }
        var b=route(true,false);b.getAsJsonObject(CapabilityEncounterPolicy.FIELD).addProperty("ignore_new_threats",true);
        assertThrows(ClientActionRequest.Rejected.class,()->wire(b));
        var unguarded=route(true,false);unguarded.remove("capability_guard");assertThrows(ClientActionRequest.Rejected.class,()->wire(unguarded));
        var low=route(true,false);low.addProperty("min_health",10);assertThrows(ClientActionRequest.Rejected.class,()->wire(low));
        var request=wire(route(true,false));var player=new CapabilityEncounterPolicy.Point(.5,64,.5);
        assertEquals("encounter_route_observation_incomplete",CapabilityEncounterPolicy.check(request,player,List.of(),1,NANO,1,NANO,false));
        assertEquals("encounter_route_observation_stale",CapabilityEncounterPolicy.check(request,player,List.of(),1,NANO,2,NANO,true));
        assertEquals("encounter_route_observation_stale",CapabilityEncounterPolicy.check(request,player,List.of(),1,NANO,1,NANO+CapabilityEncounterPolicy.MAX_SCAN_NANOS+1,true));
    }
    @Test void endermanCalmRequiresFreshCompleteBoundServerFactsRatherThanClientNullTarget() {
        Object context=new Object();String dimension="minecraft:the_end";
        for(boolean aggressive:new boolean[]{false,true})for(boolean hasTarget:new boolean[]{false,true}) {
            var row=new NativeLivingSnapshot.Row(ID,12,"minecraft:enderman",1,NANO,true,aggressive,
                    hasTarget?new NativeLivingSnapshot.Target("other",99,"minecraft:player"):null,null);
            var batch=new NativeLivingSnapshot.Batch(context,new Object(),dimension,java.util.Map.of(ID,row),true,1,"observed");
            assertEquals(!aggressive&&!hasTarget,NativeLivingSnapshot.knownCalmTargetless(batch,context,dimension,ID,12,"minecraft:enderman",1,NANO+1));
            assertFalse(NativeLivingSnapshot.knownCalmTargetless(batch,context,dimension,ID,12,"minecraft:enderman",1,NANO+250_000_001L));
            assertFalse(NativeLivingSnapshot.knownCalmTargetless(batch,new Object(),dimension,ID,12,"minecraft:enderman",1,NANO+1));
        }
        assertFalse(NativeLivingSnapshot.knownCalmTargetless(null,context,dimension,ID,12,"minecraft:enderman",1,NANO+1));
    }
    @Test void emittedNativeWireContainsProductionContractsAndOptionalActualPythonCommands() throws Exception {
        JsonArray commands=new JsonArray();commands.add(route(true,false));commands.add(route(true,true));commands.add(combat(18));commands.add(shulker());
        int pythonCommands=0;
        String fixture=System.getenv("MDC_COMBAT_COMMAND_WIRE");
        if(fixture!=null&&!fixture.isBlank()) {
            JsonObject external=JsonParser.parseString(Files.readString(Path.of(fixture))).getAsJsonObject();
            for(var command:external.getAsJsonArray("commands")){commands.add(command.deepCopy());pythonCommands++;}
        }
        JsonArray accepted=new JsonArray();
        for(var item:commands) {var parsed=wire(item.getAsJsonObject());accepted.add(parsed.original());}
        var output=new JsonObject();output.add("combat_capabilities",CapabilityCombatSafety.capabilities());output.add("accepted_commands",accepted);
        output.addProperty("python_commands_parsed",pythonCommands);
        output.addProperty("observation_scope","synthetic_repeated_samples_through_production_native_policy");
        output.addProperty("game_launched",false);
        var health=new CombatThreats.HealthGuard(BoundedCombatRequest.parse(wire(combat(18)).original()).minHealth());
        health.sample(1,NANO,20);output.addProperty("health_20_to17_reserve18",health.sample(2,NANO+50_000_000L,17).reason());
        output.addProperty("closed_raw_stale_open_animation",CapabilityCombatSafety.shellOpen(0,1));
        output.addProperty("new_drowned",check(wire(route(true,false)),List.of(entity(20,"minecraft:drowned",5,false,false)),2,NANO));
        var potential=new JsonObject();
        for(String type:List.of("minecraft:goat","minecraft:rabbit","minecraft:pufferfish"))
            potential.addProperty(type,check(wire(route(true,false)),List.of(entity(20,type,5,false,false)),2,NANO));
        output.add("new_potential_dangers",potential);
        Path path=Path.of(System.getProperty("mineclientBridge.projectDir"),"build/validation/combat-guard-wire.json");
        Files.createDirectories(path.getParent());Files.writeString(path,BridgeJson.toJson(output)+"\n");
    }
}
