package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** One process-local, one-shot ledger. No position/velocity mutations or budget resets. */
final class MovementBudgetLedger {
    static final double CAP = 32, RESERVE = 2, MAX_STEP = .55, MAX_SPEED = .35;
    static final String MODE = "dry_flat_self_walk_v1";
    final String bundleId, session, worldGeneration, playerUuid;
    final Object world, player;
    final long startedNano;
    final Thread ownerThread=Thread.currentThread();
    private final double originX,originY,originZ;
    private double x,y,z, distance;
    private long mutations, samples;
    private int moveDepth, moveMutations, settledTicks;
    private double moveLimit,tickDistance;
    private String state="armed", reason="armed";
    private boolean coverage=true,furnaceXpAllowed;
    private long endedNano;

    MovementBudgetLedger(String id,String session,String generation,String uuid,Object world,Object player,
            double x,double y,double z,long nano) {
        bundleId=id;this.session=session;worldGeneration=generation;playerUuid=uuid;
        this.world=world;this.player=player;this.x=x;this.y=y;this.z=z;startedNano=nano;originX=x;originY=y;originZ=z;
        if(!finite(x,y,z))invalidate("movement_budget_invalid_position");
    }
    void allowFurnaceXp(){if(usable())furnaceXpAllowed=true;}
    boolean furnaceXpAllowed(){return furnaceXpAllowed;}
    boolean observing(){return !state.equals("sealed");}
    boolean usable(){return state.equals("armed");}
    boolean invalid(){return state.equals("invalid");}
    boolean stopping(){return state.equals("stopping");}
    String reason(){return reason;}
    int depth(){return moveDepth;}
    double distance(){return distance;}
    void invalidate(String why){if(!state.equals("sealed")&&!state.equals("invalid")){state="invalid";reason=why;coverage=false;}}
    void sample(Object world,Object player,String session,double x,double y,double z,boolean settled,boolean postTick) {
        if(!observing())return;
        samples++;
        if(this.world!=world||this.player!=player||!this.session.equals(session)){invalidate("movement_budget_context_changed");return;}
        if(!finite(x,y,z)){invalidate("movement_budget_invalid_position");return;}
        if(x!=this.x||y!=this.y||z!=this.z){invalidate("movement_budget_unobserved_position_change");this.x=x;this.y=y;this.z=z;}
        if(moveDepth!=0)invalidate("movement_budget_unfinished_move");
        if(postTick)settledTicks=settled?Math.min(3,settledTicks+1):0;
    }
    void beginTick(){if(observing()){if(moveDepth!=0)invalidate("movement_budget_unfinished_move");tickDistance=0;}}
    void beginMove(boolean self,double requestedX,double requestedY,double requestedZ) {
        if(!observing())return;
        if(moveDepth++!=0)invalidate("movement_budget_reentrant_move");
        moveMutations=0;
        moveLimit=Math.hypot(requestedX,requestedZ);
        if(!self)invalidate("movement_budget_external_move");
        if(!finite(requestedX,requestedY,requestedZ)||moveLimit>MAX_STEP||requestedY>0||requestedY<-.09)
            invalidate("movement_budget_move_envelope_changed");
    }
    void position(double x,double y,double z) {
        if(!observing())return;
        if(!finite(x,y,z)){invalidate("movement_budget_invalid_position");return;}
        double dx=x-this.x,dy=y-this.y,dz=z-this.z;
        if(dx==0&&dy==0&&dz==0)return;
        double segment=Math.hypot(Math.hypot(dx,dy),dz);
        if(!Double.isFinite(segment)||!Double.isFinite(distance+segment)){invalidate("movement_budget_invalid_distance");this.x=x;this.y=y;this.z=z;return;}
        // Never silently turn a correction into accepted voluntary distance.
        // Known displacement is still retained as diagnostic lower-bound evidence.
        if(moveDepth!=1||++moveMutations!=1)invalidate("movement_budget_external_position_change");
        if(dy!=0||segment>moveLimit+1e-7||segment>MAX_STEP+1e-7)invalidate("movement_budget_position_envelope_changed");
        distance+=segment;tickDistance+=segment;mutations++;settledTicks=0;
        if(tickDistance>MAX_STEP+1e-7)invalidate("movement_budget_tick_motion_envelope_changed");
        this.x=x;this.y=y;this.z=z;
        if(!Double.isFinite(distance)||distance>CAP)invalidate("movement_budget_exceeded");
        else if(state.equals("armed")&&distance>=CAP-RESERVE){state="stopping";reason="movement_budget_reserve_reached";}
    }
    void endMove(){if(!observing())return;if(moveDepth!=1)invalidate("movement_budget_reentrant_move");moveDepth=Math.max(0,moveDepth-1);}
    boolean canSeal(){return (usable()||stopping())&&settledTicks>=3&&moveDepth==0&&distance<=CAP;}
    void seal(long nano){if(!canSeal())throw new ClientActionRequest.Rejected(409,"movement_budget_not_settled");state="sealed";reason="movement_budget_sealed";endedNano=nano;}
    JsonObject snapshot() {
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("mode",MODE);
        j.addProperty("bundle_id",bundleId);j.addProperty("action_session",session);
        j.addProperty("world_generation",worldGeneration);j.addProperty("player_uuid",playerUuid);
        j.addProperty("status",state);j.addProperty("reason",reason);j.addProperty("actual_distance",distance);
        j.addProperty("max_distance",CAP);j.addProperty("remaining_distance",Math.max(0,CAP-distance));
        j.addProperty("stop_reserve",RESERVE);j.addProperty("metric","client_self_move_polyline");
        j.addProperty("coverage_complete",coverage);j.addProperty("moving_accepted",coverage&&!invalid());
        j.addProperty("covers_armed_interval_only",true);
        JsonObject origin=new JsonObject();origin.addProperty("x",originX);origin.addProperty("y",originY);origin.addProperty("z",originZ);j.add("arm_origin",origin);j.addProperty("position_mutations",mutations);
        j.addProperty("boundary_samples",samples);j.addProperty("settled_ticks",settledTicks);
        j.addProperty("started_nano",Long.toString(startedNano));j.addProperty("ended_nano",endedNano==0?null:Long.toString(endedNano));
        j.addProperty("furnace_xp_allowed",furnaceXpAllowed);
        j.addProperty("no_reset",true);j.addProperty("all_cause_physical_cap",false);
        return j;
    }
    private static boolean finite(double x,double y,double z){return Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z);}
}
