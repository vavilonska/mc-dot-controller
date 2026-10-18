package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Production pure episode + Gson schema/model fixture. Does not execute game-bound status(). */
public final class FallRescueStatusFixtures {
 static final String ARM="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
 static JsonObject status(FallRescueEpisode p,boolean terminal,int age){
  JsonObject j=new JsonObject();j.addProperty("fall_rescue_schema_version",1);j.addProperty("status",terminal?"disarmed":p==null?"armed":"rescuing");j.addProperty("reason","fixture_model");
  j.addProperty("armed",!terminal);j.addProperty("input_owned",p!=null&&!terminal);j.addProperty("automation_blocked",p!=null&&!terminal);j.addProperty("unknown_outcome_quarantined",false);
  j.addProperty("arm_revision",1);j.addProperty("episodes_used",p==null?0:1);j.addProperty("no_auto_resume",true);j.addProperty("remaining_ms",terminal?0:5000);
  j.addProperty("arm_id",ARM);j.addProperty("owner_id","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");j.addProperty("action_session","session");j.addProperty("world_generation","world");j.addProperty("player_uuid","player");
  if(p!=null){JsonObject e=new JsonObject();e.addProperty("episode_id",p.id);e.addProperty("outcome",p.outcome());e.addProperty("age_ticks",age);e.addProperty("hotbar_slot",1);
   e.addProperty("dispatch_attempted",p.attempted());e.addProperty("packet_send_fence_passed",p.packetSent());e.addProperty("client_prediction_water",p.clientWater());e.addProperty("server_water_observed",p.serverWater());e.addProperty("server_bucket_transition_observed",p.serverBucket());e.addProperty("server_landed_alive_observed",p.landedAlive());e.addProperty("rescue_confirmed",p.confirmed());
   e.addProperty("confirmation_basis","correlated_readonly_integrated_server_state_after_pre_dispatch_baseline");e.addProperty("interaction_result",p.attempted()?"success":null);e.addProperty("baseline_server_tick",100);
   JsonObject target=new JsonObject();target.addProperty("x",1);target.addProperty("y",64);target.addProperty("z",1);e.add("water_target",target);j.add(terminal?"last_episode":"episode",e);}
  return j;
 }
 public static void main(String[] args)throws Exception{
  JsonArray rows=new JsonArray();rows.add(status(null,false,0));var p=new FallRescueEpisode(ARM+":1",0);rows.add(status(p,false,1));p.attempt();p.packet();p.predictedWater(true);rows.add(status(p,false,2));p.serverObservation(true,true,false);rows.add(status(p,false,3));p.serverObservation(true,true,true);rows.add(status(p,true,4));
  Files.writeString(Path.of(args[0]),new GsonBuilder().serializeNulls().setPrettyPrinting().create().toJson(rows)+"\n");
 }
}
