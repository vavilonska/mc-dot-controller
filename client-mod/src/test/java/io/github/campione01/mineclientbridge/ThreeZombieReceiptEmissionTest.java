package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Actual native serializer/state-machine receipts. Synthetic snapshots, no Minecraft runtime. */
class ThreeZombieReceiptEmissionTest {
    @Test void emitThreeModeNativeReceiptsForBothRealWireValidators() throws Exception {
        JsonArray cases=new JsonArray();
        for(String name:List.of("running","succeeded","failed","cancelled","cleanup_failed","projectile","projectile_unknown","pause_unknown")) {
            var registry=new ActionRegistry();var body=ThreeZombieEncounterTest.request();
            body.addProperty("expected_action_session",registry.session);
            if(name.equals("pause_unknown"))body.addProperty("encounter_pause_on_terminal",true);
            var request=ClientActionRequest.parse(body);var parsed=BoundedCombatRequest.parse(body);
            var entry=registry.begin(request);entry.result.addProperty("world_generation",parsed.world());
            JsonObject combat=new JsonObject();entry.result.add("combat",combat);CombatInitialEvidence.initialize(parsed,combat,20,20);
            var clock=new AtomicLong(1_000_000_000L);var health=new CombatThreats.HealthGuard();
            var owner=new BoundedEncounter(parsed.encounter(),combat,0,64,0,30_000_000_000L,clock::get,health);
            String terminal=null,reason=null;
            for(int tick=0;tick<(name.equals("succeeded")||name.equals("cleanup_failed")?3:1);tick++) {
                clock.set(1_000_000_000L+tick*50_000_000L);
                var snapshot=new CombatThreats.Snapshot(ThreeZombieEncounterTest.triple(10),clock.get(),tick,false,!name.equals("failed"),name.equals("projectile")?1:name.equals("projectile_unknown")?-1:0);
                var motion=new CombatRecovery.Motion(0,64,0,0,0,0,true);
                var step=owner.tick(tick,snapshot,motion,health.sample(tick,clock.get(),20),
                    (a,b)->{throw new AssertionError("Clearance fixture must not plan movement");},()->null,(a,b)->{});
                terminal=step.terminal();reason=step.reason();
            }
            if(name.equals("cancelled")||name.equals("pause_unknown")) {terminal="cancelled";reason="encounter_paused_risk_remaining";}
            if(terminal!=null) {
                boolean released=!name.equals("cleanup_failed");owner.terminal(released?terminal:"failed",released?reason:"input_release_unconfirmed");
                registry.finishAfterCleanup(terminal,reason,released);
            }
            if(name.equals("pause_unknown")) {
                var count=new int[]{0};
                EncounterTerminalPause.afterTerminal(entry,registry.session,p->{count[0]++;throw new IllegalStateException("synthetic_unknown");});
                EncounterTerminalPause.afterTerminal(entry,registry.session,p->{count[0]++;throw new AssertionError("Must not retry");});assertEquals(1,count[0]);
            }
            JsonObject test=new JsonObject();test.addProperty("name",name);test.add("request",body);test.add("receipt",registry.status(request.id()));cases.add(test);
            assertEquals(name.equals("running")?"running":name.equals("succeeded")?"succeeded":name.equals("cancelled")||name.equals("pause_unknown")?"cancelled":"failed",registry.status(request.id()).get("status").getAsString());
        }
        var result=new JsonObject();result.add("cases",cases);result.addProperty("observations","synthetic_offline_no_game_physics");
        Path target=Path.of(System.getProperty("mineclientBridge.projectDir"),"build/encounter-fixtures/three-zombie-receipts.json");
        Files.createDirectories(target.getParent());Files.writeString(target,result.toString()+"\n");assertEquals(8,cases.size());
    }
}
