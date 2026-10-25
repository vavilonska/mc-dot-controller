package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.util.List;

/** Offline real request/registry + pure production-policy checks. Does not claim a game attack. */
public final class BlazeEscortChecks {
    static int checks;
    static void check(boolean b,String why){checks++;if(!b)throw new AssertionError(why);}
    static void rejects(Runnable f,String why){checks++;try{f.run();throw new AssertionError("accepted: "+why);}catch(ClientActionRequest.Rejected expected){}}
    static JsonObject request(){return JsonParser.parseString("""
       {"action":"follow_path","action_id":"offline-blaze-001","timeout_ms":60000,
        "expected_world_generation":"00000000-0000-0000-0000-000000000001",
        "expected_player_uuid":"00000000-0000-0000-0000-000000000002",
        "expected_action_session":"00000000-0000-0000-0000-000000000003",
        "expected_navigation_epoch":0,"expected_origin":{"x":0.5,"y":64,"z":0.5},
        "waypoints":[{"x":1.5,"y":64,"z":0.5},{"x":2.5,"y":64,"z":0.5}],
        "sneak":false,"blaze_guard":{"schema_version":1,"known_route":true,"shield":true,
          "stop_health":6,"maximum_observed_damage":20,"continuous_fire_ms":12000,
          "engage_timeout_ms":30000,"arrival_hold_ms":1000}}
       """).getAsJsonObject();}
    static BlazeEscortPolicy policy(){return new BlazeEscortPolicy(20,6,20,12000,30000);}
    static BlazeEscortPolicy.Contact contact(String id,boolean reach,boolean aggro,double d){return new BlazeEscortPolicy.Contact(id,id.hashCode()&0x7fffffff,"minecraft:blaze",d,true,reach,aggro);}
    public static void main(String[] args){
        JsonObject body=request();ClientActionRequest r=ClientActionRequest.parse(body);
        check(NativeBlazeEscort.validate(r).shield(),"explicit shield");
        check(r.timeoutMs()==60000&&r.waypoints().size()==2,"original timeout/route preserved");
        JsonObject ordinary=body.deepCopy();ordinary.remove("blaze_guard");
        check(NativeBlazeEscort.validate(ClientActionRequest.parse(ordinary))==null,"ordinary path unchanged");
        JsonObject bad=body.deepCopy();bad.getAsJsonObject("blaze_guard").addProperty("known_route",false);final JsonObject unknownRoute=bad;rejects(()->ClientActionRequest.parse(unknownRoute),"unknown route");
        bad=body.deepCopy();bad.remove("expected_navigation_epoch");final JsonObject noEpoch=bad;rejects(()->ClientActionRequest.parse(noEpoch),"binding pair");
        bad=body.deepCopy();bad.addProperty("action","recover_environment");final JsonObject recovery=bad;rejects(()->ClientActionRequest.parse(recovery),"not recover environment");
        bad=body.deepCopy();bad.getAsJsonObject("blaze_guard").addProperty("auto_teleport",true);final JsonObject extra=bad;rejects(()->ClientActionRequest.parse(extra),"closed scope");
        check(!BoundedCombatRequest.REQUEST_TYPES.contains("minecraft:blaze"),"generic combat whitelist unchanged");

        var near=contact("near",true,false,2.5);var aggro=contact("aggro",false,true,9);var unknown=contact("unknown",false,false,1.5);
        check(BlazeEscortPolicy.candidate(List.of(unknown))==null,"unknown does not fabricate aggro");
        check(BlazeEscortPolicy.candidate(List.of(aggro))==aggro,"true target-player triggers outside reach");
        check(BlazeEscortPolicy.candidate(List.of(aggro,near))==near,"reachable has priority over far aggro");
        check(BlazeEscortPolicy.candidate(List.of(near))==near,"reach independent of unknown server source");
        var p=policy();p.acquire(near,0);check(p.phase==BlazeEscortPolicy.Phase.ENGAGING,"navigate triggers native engage");
        check(!p.mayAttack(1,false,1,false),"wrong ray no attack");
        check(!p.mayAttack(1,true,.94,false),"insufficient native cooldown");
        check(!p.mayAttack(1,true,1,true),"shield must lower before attack");
        check(p.mayAttack(1,true,.95,false),"fresh ray full enough cooldown");p.attackAttempt(1);
        check(!p.mayAttack(1,true,1,false)&&p.attacks==1,"same tick exactly one attack");
        p.acquire(aggro,1);check(p.targetUuid.equals("near"),"no locked-target replacement");
        p.targetDead();check(p.kills==1&&p.phase==BlazeEscortPolicy.Phase.NAVIGATING,"real dead resumes route");
        p.acquire(aggro,2);p.targetLost();check(p.kills==1&&p.lostTargets==1&&p.phase==BlazeEscortPolicy.Phase.RETURNING,"missing is not kill and returns");
        p=policy();p.health(19.3,false,false,1);check(p.phase==BlazeEscortPolicy.Phase.NAVIGATING,"ordinary damage tolerated");
        p.health(20,false,false,2);p.health(19,false,false,3);check(Math.abs(p.observedDamage-1.7)<.0001,"healing does not erase observed damage");
        p.health(19,true,false,4);check(p.phase==BlazeEscortPolicy.Phase.NAVIGATING,"first fire not immediate abort");
        p.health(18,true,false,4+12_000_000_000L);check(p.phase==BlazeEscortPolicy.Phase.RETURNING,"continuous fire budget");
        p=policy();p.health(6,false,false,1);check(p.phase==BlazeEscortPolicy.Phase.RETURNING,"absolute low health returns");
        p=policy();p.health(20,false,true,1);check(p.phase==BlazeEscortPolicy.Phase.RETURNING,"liquid emergency returns");
        p=policy();p.acquire(near,10);p.deadline(10+30_000_000_000L);check(p.phase==BlazeEscortPolicy.Phase.RETURNING,"original engagement timer bounded");

        var cover=new ClientActionRequest.Point(.5,64,.5,false);
        var route=new BlazeEscortPolicy.Route(r.waypoints(),cover);
        check(route.next==0,"starts at first waypoint");route.arrived();
        p=policy();p.acquire(near,0);p.targetDead();check(route.next==1,"combat does not refund completed waypoint");
        route.beginReturn();check(route.retreat().equals(r.waypoints().get(0)),"return only completed prefix, excludes unvisited second point");
        check(!route.returnArrived()&&route.retreat().equals(cover),"then actual original cover");
        check(route.returnArrived(),"cover terminates return");
        var first=new BlazeEscortPolicy.Route(r.waypoints(),cover);first.beginReturn();check(first.retreat().equals(cover),"partial first segment returns directly along actual walked part");

        // r2 reproduces trial1's already-walked route; no enemy-created point is inserted.
        var trial=List.of(new ClientActionRequest.Point(4.165848892,-60,.5,false),
            new ClientActionRequest.Point(4.165848892,-60,6.540298517,false),
            new ClientActionRequest.Point(.2841409897,-60,6.540298517,false));
        var actualTrigger=new ClientActionRequest.Point(3.409,-60,.555,false);
        check(BlazeEscortPolicy.routeCanReach(trial,0,actualTrigger,1.62,.2,-60,8.2,.8,-58.2,8.8,3),"trial1 ranged aggro has reachable original route ahead");
        check(!BlazeEscortPolicy.routeCanReach(trial,0,actualTrigger,1.62,.2,-50,8.2,.8,-48.2,8.8,3),"floating target does not create airborne pursuit");
        check(!BlazeEscortPolicy.routeCanReach(trial,0,actualTrigger,1.62,-15,-60,8.2,-14.4,-58.2,8.8,3),"off-route target does not invent approach");
        check(!BlazeEscortPolicy.routeCanReach(trial,trial.size(),actualTrigger,1.62,.2,-60,8.2,.8,-58.2,8.8,3),"exhausted route has no new pursuit point");
        check(BlazeEscortPolicy.routeCanReach(List.of(new ClientActionRequest.Point(16,64,0,false)),0,new ClientActionRequest.Point(0,64,0,false),1.62,7.7,64,2.5,8.3,65.8,3.1,3),"segment interior, not only distant endpoints, can enter reach");
        check(!BlazeEscortPolicy.routeCanReach(List.of(new ClientActionRequest.Point(16,64,0,false)),0,new ClientActionRequest.Point(0,64,0,false),1.62,7.7,64,2.5,8.3,65.8,3.1,2.4),"actual smaller reach is not expanded");
        check(Math.abs(BlazeEscortPolicy.segmentDistanceSquared(new double[]{0,0,0},new double[]{10,0,0},new double[]{4,2,-1},new double[]{6,3,1})-4)<1e-10,"exact segment AABB minimum");
        var engagingRoute=new BlazeEscortPolicy.Route(trial,actualTrigger);p=policy();p.acquire(aggro,100);
        engagingRoute.arrived();p.acquire(near,101);
        check(engagingRoute.next==1&&p.targetUuid.equals("aggro")&&p.engagedAt==100,"real original waypoint progress preserves target and engagement clock");
        engagingRoute.beginReturn();check(engagingRoute.retreat().equals(trial.get(0)),"approach may return only actually completed prefix");
        p.deadline(100+30_000_000_000L);check(p.phase==BlazeEscortPolicy.Phase.RETURNING,"moving approach never refreshes engagement deadline");
        var progress=new BlazeEscortPolicy.Progress();check(!progress.stuck(8,true,0),"progress initial sample");
        boolean catchupStuck=false;for(int i=1;i<=80;i++)catchupStuck|=progress.stuck(8,true,i*1_000_000L);
        check(!catchupStuck,"80 catch-up ticks are not four seconds without progress");
        boolean slowStuck=false;for(int i=1;i<=20;i++)slowStuck|=progress.stuck(8-i*.03,true,i*1_000_000_000L);
        check(!slowStuck,"bounded steady shield-slow progress keeps navigation alive");
        check(progress.stuck(7.4,true,24_000_000_000L),"no real progress for four seconds is stuck");
        progress.reset();check(!progress.stuck(20,true,25_000_000_000L),"next waypoint resets navigation baseline once");
        progress.reset();check(!progress.stuck(20,true,50_000_000_000L),"intentional stationary combat does not consume next approach progress interval");
        check(FallRescuePolicy.PREEMPTIBLE.contains(r.action()),"opt-in remains follow_path for explicit FallRescue preemption");

        // Real production PathSteering: an enemy pick must not reset smooth route turning each tick.
        var eastGoal=new ClientActionRequest.Point(4.165848892,-60,.5,false);
        float navYaw=20;double oldX=3.17,oldZ=.60,newX=oldX,newZ=oldZ;
        double oldBest=10,newBest=10;
        for(int t=0;t<100;t++) {
            float targetYaw=(float)Math.toDegrees(Math.atan2(-(.5-oldX),8.5-oldZ));
            var wrong=PathSteering.toward(oldX,-60,oldZ,targetYaw,true,false,eastGoal,true);
            oldX+=-Math.sin(Math.toRadians(wrong.yaw()))*wrong.forward()*.06;
            oldZ+=Math.cos(Math.toRadians(wrong.yaw()))*wrong.forward()*.06;
            var right=PathSteering.toward(newX,-60,newZ,navYaw,true,false,eastGoal,true);
            navYaw=right.yaw();
            newX+=-Math.sin(Math.toRadians(navYaw))*right.forward()*.06;
            newZ+=Math.cos(Math.toRadians(navYaw))*right.forward()*.06;
            oldBest=Math.min(oldBest,Math.hypot(eastGoal.x()-oldX,eastGoal.z()-oldZ));
            newBest=Math.min(newBest,Math.hypot(eastGoal.x()-newX,eastGoal.z()-newZ));
        }
        check(oldBest>.6,"trial4 reproduced: resetting yaw to enemy prevents original east waypoint arrival");
        check(newBest<=.23,"preserved navigation yaw converges to same original waypoint under shield-speed input");
        var turn1=PathSteering.toward(0,64,0,90,true,false,new ClientActionRequest.Point(0,64,2,false),true);
        var turn2=PathSteering.toward(0,64,0,turn1.yaw(),true,false,new ClientActionRequest.Point(0,64,2,false),true);
        check(turn1.yaw()==45&&turn2.yaw()==0,"smooth turn limit remains 45 and accumulates instead of resetting");

        Object ctx=new Object(),serverLevel=new Object();long sampleNano=5_000_000_000L;
        var deadRow=new NativeLivingSnapshot.Row("dead-blaze",91,"minecraft:blaze",500,sampleNano,false,false,null,null);
        var deadBatch=new NativeLivingSnapshot.Batch(ctx,serverLevel,"minecraft:overworld",java.util.Map.of("dead-blaze",deadRow),true,1,"observed");
        var deathProof=NativeBlazeEscort.serverDeathEvidence(deadBatch,ctx,"minecraft:overworld","generation","player","dead-blaze",91,500,sampleNano+10);
        check(deathProof!=null&&deathProof.get("entity_uuid").getAsString().equals("dead-blaze")&&!deathProof.get("alive").getAsBoolean(),"fresh exact server death survives stale client health/removal");
        check(deathProof.get("source").getAsString().equals("integrated_server_tick")&&deathProof.get("source_nano").getAsString().equals(Long.toString(sampleNano)),"individual death proof retains actual source timestamp");
        check(NativeBlazeEscort.serverDeathEvidence(deadBatch,new Object(),"minecraft:overworld","generation","player","dead-blaze",91,500,sampleNano+10)==null,"different context is not death");
        check(NativeBlazeEscort.serverDeathEvidence(deadBatch,ctx,"minecraft:overworld","generation","player","other-blaze",91,500,sampleNano+10)==null,"missing/unloaded UUID is not a kill");
        check(NativeBlazeEscort.serverDeathEvidence(deadBatch,ctx,"minecraft:overworld","generation","player","dead-blaze",92,500,sampleNano+10)==null,"reused client ID is not target death");
        check(NativeBlazeEscort.serverDeathEvidence(deadBatch,ctx,"minecraft:overworld","generation","player","dead-blaze",91,500,sampleNano+250_000_001L)==null,"expired death source not accepted");
        check(NativeBlazeEscort.serverDeathEvidence(deadBatch,ctx,"minecraft:overworld","generation","player","dead-blaze",91,506,sampleNano+10)==null,"source tick mismatch remains unknown");
        var aliveRow=new NativeLivingSnapshot.Row("dead-blaze",91,"minecraft:blaze",500,sampleNano,true,false,null,null);
        var aliveBatch=new NativeLivingSnapshot.Batch(ctx,serverLevel,"minecraft:overworld",java.util.Map.of("dead-blaze",aliveRow),true,1,"observed");
        check(NativeBlazeEscort.serverDeathEvidence(aliveBatch,ctx,"minecraft:overworld","generation","player","dead-blaze",91,500,sampleNano+10)==null,"alive row and global achievement do not certify death");
        p=policy();p.acquire(contact("dead-blaze",false,true,8),0);p.targetDead();check(p.phase==BlazeEscortPolicy.Phase.NAVIGATING&&p.kills==1&&p.targetUuid==null,"confirmed individual death resumes original route once");

        check(!p.mayAcquire("dead-blaze")&&p.mayAcquire("another-blaze"),"confirmed dead UUID excluded even if stale client still alive");
        p.acquire(contact("dead-blaze",true,true,1),1);p.targetDead();check(p.phase==BlazeEscortPolicy.Phase.NAVIGATING&&p.kills==1,"same server death cannot reacquire or count twice");

        check(NativeBlazeEscort.validate(r).targetTypes().equals(java.util.Set.of("minecraft:blaze")),"default exact Blaze remains unchanged");
        JsonObject melee=request();melee.getAsJsonObject("blaze_guard").add("target_types",JsonParser.parseString("[\"minecraft:zombie\",\"minecraft:drowned\"]"));
        check(NativeBlazeEscort.validate(ClientActionRequest.parse(melee)).targetTypes().equals(java.util.Set.of("minecraft:zombie","minecraft:drowned")),"explicit exact registered melee types supported");
        for(String invalid:new String[]{"[]","[\"minecraft:player\"]","[\"minecraft:skeleton\"]","[\"minecraft:zombie\",\"minecraft:zombie\"]","[1]","\"minecraft:zombie\""}) {
            JsonObject wrong=request();wrong.getAsJsonObject("blaze_guard").add("target_types",JsonParser.parseString(invalid));rejects(()->ClientActionRequest.parse(wrong),"unsupported malformed or duplicate explicit types");
        }
        var zombie=new BlazeEscortPolicy.Contact("zombie-one",81,"minecraft:zombie",2,true,true,true);
        var drowned=new BlazeEscortPolicy.Contact("drowned-two",82,"minecraft:drowned",2.2,true,true,true);
        p=policy();p.acquire(zombie,10);check(p.targetType.equals("minecraft:zombie")&&p.targetUuid.equals("zombie-one"),"lock actual UUID and registered type together");
        p.acquire(drowned,11);check(p.targetUuid.equals("zombie-one"),"second nearby hostile cannot replace current target");
        p.targetDead();p.acquire(drowned,12);check(p.targetType.equals("minecraft:drowned")&&p.targetUuid.equals("drowned-two")&&p.kills==1,"after confirmed first death same task acquires second exact type");
        p.targetDead();check(p.kills==2&&p.phase==BlazeEscortPolicy.Phase.NAVIGATING,"two confirmed UUIDs then continue original route");
        var drownedDead=new NativeLivingSnapshot.Row("drowned-two",82,"minecraft:drowned",500,sampleNano,false,false,null,null);
        var drownedBatch=new NativeLivingSnapshot.Batch(ctx,serverLevel,"minecraft:overworld",java.util.Map.of("drowned-two",drownedDead),true,1,"observed");
        check(NativeBlazeEscort.serverDeathEvidence(drownedBatch,ctx,"minecraft:overworld","generation","player","drowned-two",82,"minecraft:drowned",500,sampleNano+10)!=null,"death snapshot binds actual Drowned type");
        check(NativeBlazeEscort.serverDeathEvidence(drownedBatch,ctx,"minecraft:overworld","generation","player","drowned-two",82,"minecraft:zombie",500,sampleNano+10)==null,"same UUID ID wrong registered death type is rejected");
        check(!BoundedCombatRequest.REQUEST_TYPES.contains("minecraft:drowned"),"old generic combat whitelist not modified by new opt-in feature");

        ActionRegistry registry=new ActionRegistry();var entry=registry.begin(r);
        check(registry.active()==entry&&entry.running(),"real original registry owns one task");
        check(registry.existing(r)==entry,"same ID lookup does not begin again");
        JsonObject conflict=body.deepCopy();conflict.getAsJsonObject("blaze_guard").addProperty("shield",false);
        rejects(()->registry.existing(ClientActionRequest.parse(conflict)),"same ID different payload");
        registry.finishAfterCleanup("succeeded","blaze_guard_returned_to_cover",true);
        check(!entry.running()&&registry.active()==null,"cleanup terminal releases registry owner");
        check(registry.existing(r)==entry,"terminal original ID remains same record");
        JsonObject known=new JsonObject();int[] calls={0};NativeBlazeEscort.inputAttempt(known,()->calls[0]++,()->true);
        check(calls[0]==1&&!known.has("unknown_outcome"),"known native callback clears transient uncertainty");
        JsonObject lost=new JsonObject();try{NativeBlazeEscort.inputAttempt(lost,()->calls[0]++,()->false);throw new AssertionError();}catch(IllegalStateException expected){}
        check(calls[0]==2&&lost.get("unknown_outcome").getAsBoolean()&&lost.get("requires_handoff").getAsBoolean(),"synchronous owner loss remains top-level unknown");
        try{NativeBlazeEscort.inputAttempt(lost,()->calls[0]++,()->true);throw new AssertionError();}catch(IllegalStateException expected){}
        check(calls[0]==2,"unresolved input cannot be internally repeated");
        JsonObject thrown=new JsonObject();try{NativeBlazeEscort.inputAttempt(thrown,()->{calls[0]++;throw new IllegalArgumentException();},()->true);}catch(IllegalArgumentException expected){}
        check(calls[0]==3&&thrown.get("unknown_outcome").getAsBoolean(),"exception after call preserves top-level unknown");
        var reg2=new ActionRegistry();JsonObject syncBody=request();syncBody.addProperty("action_id","sync-cancel-original");var syncEntry=reg2.begin(ClientActionRequest.parse(syncBody));
        try{NativeBlazeEscort.inputAttempt(syncEntry.result,()->reg2.finishAfterCleanup("cancelled","cancel_requested",true),()->reg2.active()==syncEntry);throw new AssertionError();}catch(IllegalStateException expected){}
        check(!syncEntry.running()&&syncEntry.result.get("unknown_outcome").getAsBoolean(),"real registry synchronous terminal retains original unknown marker");
        check(syncEntry.result.get("input_release_confirmed").getAsBoolean(),"known release independent of attack certainty");
        check(!NativeBlazeEscort.dispatchInFlight(),"throw/owner loss clears only stack guard");
        JsonObject outer=new JsonObject();NativeBlazeEscort.inputAttempt(outer,()->{
            check(NativeBlazeEscort.dispatchInFlight(),"native input owns callstack fence");
            try{NativeBlazeEscort.inputAttempt(new JsonObject(),()->calls[0]++,()->true);throw new AssertionError();}catch(IllegalStateException expected){}
            check(NativeBlazeEscort.dispatchInFlight(),"swallowed nested reject cannot clear original fence");
        },()->true);
        check(!NativeBlazeEscort.dispatchInFlight()&&!outer.has("unknown_outcome"),"known outer callback restores stack fence");
        System.out.println("BlazeEscortChecks PASS checks="+checks+"; real request/registry, pure production decision/route policy; no live game claimed");
    }
}
