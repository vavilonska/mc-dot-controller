package io.github.campione01.mineclientbridge;
/** One explicit target, one already-walked flat out/back segment, no target search/replanning. */
final class EndermanShelterPolicy {
 enum Phase { OUTBOUND, GAZING, RETURNING, FIGHTING, DONE }
 Phase phase=Phase.OUTBOUND;
 boolean aggroConfirmed,aborted,knownDead;
 String reason="armed";
 final long lureNanos,engageNanos;
 long gazeSince=-1,engagedSince=-1;
 int attacks,lastAttackTick=-1;
 final BlazeEscortPolicy health;
 EndermanShelterPolicy(double hp,double stop,double damage,long fireMs,long lureMs,long engageMs){
  health=new BlazeEscortPolicy(hp,stop,damage,fireMs,engageMs);lureNanos=lureMs*1000000L;engageNanos=engageMs*1000000L;
 }
 void health(double hp,boolean fire,boolean liquid,long now){health.health(hp,fire,liquid,now);if(health.phase==BlazeEscortPolicy.Phase.RETURNING)abort(health.reason);}
 void confirmAggro(long now){if(aborted||knownDead||phase==Phase.DONE)return;if(!aggroConfirmed){aggroConfirmed=true;engagedSince=now;}if(phase==Phase.OUTBOUND||phase==Phase.GAZING){phase=Phase.RETURNING;reason="server_target_is_player_return_to_shelter";}}
 void atPeek(long now,boolean eyeLos){if(phase!=Phase.OUTBOUND)return;if(!eyeLos){abort("no_eye_line_at_authorized_peek");return;}gazeSince=now;phase=Phase.GAZING;reason="tracking_target_eyes";}
 void gaze(long now,boolean eyeLos){if(phase!=Phase.GAZING)return;if(!eyeLos)abort("eye_line_lost_return_to_shelter");else if(now-gazeSince>=lureNanos)abort("gaze_deadline_without_server_target");}
 void deadline(long now){if(aggroConfirmed&&engagedSince>=0&&now-engagedSince>=engageNanos)abort("engagement_deadline");}
 void atCover(){if(phase!=Phase.RETURNING)return;if(aggroConfirmed&&!aborted&&!knownDead){phase=Phase.FIGHTING;reason="sheltered_stationary_melee";}else{phase=Phase.DONE;reason=knownDead?"target_dead_returned_to_shelter":reason;}}
 void abort(String why){if(phase==Phase.DONE||aborted)return;aborted=true;reason=why;phase=Phase.RETURNING;}
 void dead(){if(knownDead)return;knownDead=true;reason="target_death_observed";phase=Phase.RETURNING;}
 boolean mayAttack(int tick,boolean realRay,double cooldown,boolean usingItem,boolean freshTargetSelf){return phase==Phase.FIGHTING&&aggroConfirmed&&!aborted&&!knownDead&&freshTargetSelf&&realRay&&CombatRules.cooldownReady(cooldown)&&!usingItem&&tick!=lastAttackTick;}
 void attack(int tick){if(tick==lastAttackTick)throw new IllegalStateException("duplicate_attack_tick");lastAttackTick=tick;attacks++;}
}
