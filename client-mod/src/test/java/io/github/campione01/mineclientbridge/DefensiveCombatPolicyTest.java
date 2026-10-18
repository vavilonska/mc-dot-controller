package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
public final class DefensiveCombatPolicyTest {
    static int checks;
    static void ok(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    static JsonObject body(String mode,int window,double distance,double gain){JsonObject b=new JsonObject();b.addProperty("approach",false);b.addProperty("shield",mode.equals("shield_only"));b.addProperty("timeout_ms",window+250);JsonObject p=new DefensiveCombatPolicy(mode,window,distance,gain).json();b.add("defensive_policy",p);return b;}
    static void rejects(JsonObject b){boolean denied=false;try{DefensiveCombatPolicy.parseOptional(b);}catch(RuntimeException e){denied=true;}ok(denied);}
    public static void main(String[]args){
        DefensiveCombatPolicy shield=DefensiveCombatPolicy.parseOptional(body("shield_only",1000,0,0));ok(shield.shieldOnly());ok(!shield.mayMove(0));
        DefensiveCombatPolicy evade=DefensiveCombatPolicy.parseOptional(body("immediate_evade",2500,4,.5));ok(!evade.shieldOnly());ok(evade.mayMove(3.35));ok(!evade.mayMove(3.36));ok(!evade.mayMove(Double.NaN));ok(!evade.mayMove(-1));ok(evade.proposalDistance()==3);
        ok(!evade.elapsed(100,2_499_999_999L));ok(evade.elapsed(100,2_500_000_100L));ok(evade.separationObserved(2,2.5));ok(!evade.separationObserved(2,2.49));ok(!evade.separationObserved(Double.NaN,4));
        for(int mask=0;mask<32;mask++){boolean same=(mask&1)!=0,attack=(mask&2)!=0,player=(mask&4)!=0,offhand=(mask&8)!=0,onBlock=(mask&16)!=0;ok(DefensiveCombatPolicy.useAllowed(same,attack,player,offhand,onBlock)==(same&&!attack&&player&&offhand&&!onBlock));}
        for(int n=0;n<5;n++)for(boolean active:new boolean[]{false,true})for(boolean blocking:new boolean[]{false,true})ok(DefensiveCombatPolicy.shieldWindowObserved(n,active,blocking)==(n>=3&&active&&blocking));
        rejects(body("attack",1000,0,0));rejects(body("shield_only",299,0,0));rejects(body("shield_only",2501,0,0));rejects(body("shield_only",1000,1,0));rejects(body("immediate_evade",1000,4.01,.5));rejects(body("immediate_evade",1000,1,1));
        JsonObject b=body("shield_only",1000,0,0);b.getAsJsonObject("defensive_policy").addProperty("schema_version",true);rejects(b);
        b=body("shield_only",1000,0,0);b.addProperty("approach",true);rejects(b);b=body("shield_only",1000,0,0);b.addProperty("timeout_ms",1000);rejects(b);
        b=body("shield_only",1000,0,0);b.addProperty("encounter_mode","three_zombie");rejects(b);
        System.out.println("DefensiveCombatPolicyTest: "+checks+" checks passed");
    }
}
