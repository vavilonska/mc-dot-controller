package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Native generated wire fixtures, consumed by real Python/JS receipt validators offline. */
class EncounterReceiptEmissionTest {
    @Test void emitActualNativeEvidenceAndRegistrySerialization() throws Exception {
        JsonArray cases=new JsonArray();
        for(String name:List.of("running","succeeded","failed","cancelled","cleanup_failed")) {
            var registry=new ActionRegistry();var body=BoundedEncounterTest.request();
            body.addProperty("expected_action_session",registry.session);
            var request=ClientActionRequest.parse(body);var parsed=BoundedCombatRequest.parse(body);
            var entry=registry.begin(request);entry.result.addProperty("world_generation",parsed.world());
            JsonObject combat=new JsonObject();entry.result.add("combat",combat);
            CombatInitialEvidence.initialize(parsed,combat,20,20);
            var clock=new AtomicLong(1_000_000_000L);var health=new CombatThreats.HealthGuard();
            var owner=new BoundedEncounter(parsed.encounter(),combat,0,64,0,30_000_000_000L,clock::get,health);
            String terminal=null,reason=null;
            for(int tick=0;tick<(name.equals("succeeded")||name.equals("cleanup_failed")?3:1);tick++) {
                clock.set(1_000_000_000L+tick*50_000_000L);
                var snapshot=new CombatThreats.Snapshot(BoundedEncounterTest.pair(10),clock.get(),tick,false,!name.equals("failed"));
                var motion=new CombatRecovery.Motion(0,64,0,0,0,0,true);
                var step=owner.tick(tick,snapshot,motion,health.sample(tick,clock.get(),20),
                        (a,b)->{throw new AssertionError("Clearance fixture must not plan movement");},()->null,(a,b)->{});
                terminal=step.terminal();reason=step.reason();
            }
            if(name.equals("cancelled")) { terminal="cancelled";reason="encounter_paused_risk_remaining"; }
            if(terminal!=null) {
                boolean released=!name.equals("cleanup_failed");
                owner.terminal(released?terminal:"failed",released?reason:"input_release_unconfirmed");
                registry.finishAfterCleanup(terminal,reason,released);
            }
            JsonObject test=new JsonObject();test.addProperty("name",name);test.add("request",body);
            test.add("receipt",registry.status(request.id()));cases.add(test);
            assertEquals(name.equals("cleanup_failed")?"failed":name,registry.status(request.id()).get("status").getAsString());
        }
        var result=new JsonObject();result.add("cases",cases);result.addProperty("observations","synthetic_offline_no_game_physics");
        Path target=Path.of(System.getProperty("mineclientBridge.projectDir"),"build/encounter-fixtures/receipts.json");
        Files.createDirectories(target.getParent());Files.writeString(target,result.toString()+"\n");
        assertEquals(5,cases.size());
    }
}
