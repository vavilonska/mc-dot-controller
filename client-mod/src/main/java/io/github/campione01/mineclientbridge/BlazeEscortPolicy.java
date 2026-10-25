package io.github.campione01.mineclientbridge;

import java.util.Comparator;
import java.util.List;

/** Pure event decisions shared by the real tick adapter and offline checks. No game writes. */
final class BlazeEscortPolicy {
    enum Phase { NAVIGATING, HOLDING, ENGAGING, RETURNING, DONE }
    record Contact(String uuid, int entityId, String type, double eyeDistance, boolean alive,
                   boolean reachableVisible, boolean targetPlayerKnown) { }
    final double stopHealth, maximumDamage;
    final long fireNanos, engageNanos;
    Phase phase=Phase.NAVIGATING;
    String targetUuid, targetType, reason="armed";
    int targetId=-1, attacks, kills, lostTargets, lastAttackTick=-1;
    final java.util.Set<String> confirmedDead=new java.util.HashSet<>();
    double previousHealth, observedDamage;
    long firstFire=-1, engagedAt;
    BlazeEscortPolicy(double health,double stopHealth,double maximumDamage,long fireMs,long engageMs) {
        this.previousHealth=health;this.stopHealth=stopHealth;this.maximumDamage=maximumDamage;
        this.fireNanos=fireMs*1_000_000L;this.engageNanos=engageMs*1_000_000L;
    }
    static Contact candidate(List<Contact> contacts) {
        return contacts.stream().filter(c->c.alive && (c.reachableVisible || c.targetPlayerKnown))
            .min(Comparator.comparingInt((Contact c)->c.reachableVisible?0:1).thenComparingDouble(Contact::eyeDistance)).orElse(null);
    }
    void health(double current,boolean fire,boolean liquid,long now) {
        if(!Double.isFinite(current) || current<=0){beginReturn("player_health_unavailable");return;}
        observedDamage+=Math.max(0,previousHealth-current);previousHealth=current;
        if(fire && firstFire<0)firstFire=now;
        if(!fire)firstFire=-1; // Continuous burning, not an invented immunity/automatic extinguishing claim.
        if(phase==Phase.RETURNING || phase==Phase.DONE)return;
        if(liquid)beginReturn("environment_hazard");
        else if(current<=stopHealth)beginReturn("health_floor");
        else if(observedDamage>=maximumDamage)beginReturn("observed_damage_budget");
        else if(firstFire>=0 && now-firstFire>=fireNanos)beginReturn("continuous_fire_budget");
    }
    boolean mayAcquire(String uuid){return !confirmedDead.contains(uuid);}
    void acquire(Contact c,long now) {
        if(c==null || !mayAcquire(c.uuid) || phase==Phase.RETURNING || phase==Phase.DONE || phase==Phase.ENGAGING)return;
        targetUuid=c.uuid;targetId=c.entityId;targetType=c.type;engagedAt=now;phase=Phase.ENGAGING;
        reason=c.reachableVisible?(c.type.equals("minecraft:blaze")?"reachable_blaze":"reachable_supported_target"):"server_target_is_player";
    }
    void targetDead() {if(phase==Phase.ENGAGING){if(confirmedDead.add(targetUuid))kills++;clearTarget();phase=Phase.NAVIGATING;reason="target_dead_observed";}}
    void targetLost() {if(phase==Phase.ENGAGING){lostTargets++;beginReturn("target_missing_not_a_kill");}}
    void deadline(long now) {if(phase==Phase.ENGAGING && now-engagedAt>=engageNanos)beginReturn("engagement_deadline_return");}
    boolean mayAttack(int tick,boolean ray,double cooldown,boolean usingItem) {
        return phase==Phase.ENGAGING && ray && CombatRules.cooldownReady(cooldown) && !usingItem && tick!=lastAttackTick;
    }
    void attackAttempt(int tick) {if(tick==lastAttackTick)throw new IllegalStateException("duplicate_attack_tick");lastAttackTick=tick;attacks++;}
    void beginReturn(String why) {if(phase!=Phase.RETURNING && phase!=Phase.DONE){phase=Phase.RETURNING;reason=why;}}
    void clearTarget(){targetUuid=null;targetType=null;targetId=-1;}
    /** Only original route segments may justify closing. Geometric possibility is not ray/terrain authority. */
    static boolean routeCanReach(List<ClientActionRequest.Point> points,int next,ClientActionRequest.Point from,double eyeHeight,
            double minX,double minY,double minZ,double maxX,double maxY,double maxZ,double reach) {
        double[] low={minX,minY,minZ},high={maxX,maxY,maxZ};
        for(int i=next;i<points.size();i++) {
            var to=points.get(i);
            if(segmentDistanceSquared(new double[]{from.x(),from.y()+eyeHeight,from.z()},
                    new double[]{to.x(),to.y()+eyeHeight,to.z()},low,high)<=reach*reach)return true;
            from=to;
        }
        return false;
    }
    /** Exact piecewise-quadratic segment-to-AABB distance; no expanded reach or target-created waypoint. */
    static double segmentDistanceSquared(double[] a,double[] b,double[] low,double[] high) {
        double[] d={b[0]-a[0],b[1]-a[1],b[2]-a[2]};
        var cuts=new java.util.ArrayList<Double>();cuts.add(0.0);cuts.add(1.0);
        for(int i=0;i<3;i++)if(d[i]!=0)for(double bound:new double[]{low[i],high[i]}) {
            double t=(bound-a[i])/d[i];if(t>0&&t<1)cuts.add(t);
        }
        java.util.Collections.sort(cuts);double best=Double.POSITIVE_INFINITY;
        for(int j=1;j<cuts.size();j++) {
            double left=cuts.get(j-1),right=cuts.get(j),mid=(left+right)/2,A=0,B=0;
            for(int i=0;i<3;i++) {
                double value=a[i]+d[i]*mid;
                if(value<low[i]||value>high[i]){double bound=value<low[i]?low[i]:high[i];A+=d[i]*d[i];B+=d[i]*(a[i]-bound);}
            }
            double t=A==0?mid:Math.max(left,Math.min(right,-B/A)),sum=0;
            for(int i=0;i<3;i++){double value=a[i]+d[i]*t,delta=value-Math.max(low[i],Math.min(high[i],value));sum+=delta*delta;}
            best=Math.min(best,sum);
        }
        return best;
    }
    /** Real progress survives shield slow-down and catch-up ticks; the wall clock bound never resets without improvement. */
    static final class Progress {
        double best=Double.POSITIVE_INFINITY;long improvedAt=-1;
        void reset(){best=Double.POSITIVE_INFINITY;improvedAt=-1;}
        boolean stuck(double distance,boolean grounded,long now) {
            if(improvedAt<0 || distance<best-.025){best=distance;improvedAt=now;}
            return grounded && now-improvedAt>=4_000_000_000L;
        }
    }
    /** A known successful waypoint is advanced once, never replayed after a combat interruption. */
    static final class Route {
        final List<ClientActionRequest.Point> points;
        final ClientActionRequest.Point cover;
        int next, returning=-2;
        Route(List<ClientActionRequest.Point> points,ClientActionRequest.Point cover){this.points=List.copyOf(points);this.cover=cover;}
        boolean outboundDone(){return next>=points.size();}
        ClientActionRequest.Point outbound(){return points.get(next);}
        void arrived(){if(outboundDone())throw new IllegalStateException("route_already_complete");next++;}
        void beginReturn(){if(returning==-2)returning=next-1;}
        ClientActionRequest.Point retreat(){return returning>=0?points.get(returning):cover;}
        boolean returnArrived(){if(returning<0)return true;returning--;return false;}
    }
}
