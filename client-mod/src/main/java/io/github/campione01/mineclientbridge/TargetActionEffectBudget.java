package io.github.campione01.mineclientbridge;

/** Pure single-action budget. Failed/uncertain reservations never become reusable. */
final class TargetActionEffectBudget {
    enum Effect { MELEE, DRAW, BOW_RELEASE, SHIELD_USE, SHIELD_RELEASE, SHIELD_CLEANUP, ABORT, SWING }
    private final boolean ranged,shield;
    private boolean poisoned,offenseReserved,drawReserved,abortReserved;
    private int shieldUses,shieldReleases;
    private final int[] local=new int[Effect.values().length],packets=new int[Effect.values().length];
    TargetActionEffectBudget(boolean ranged,boolean shield){this.ranged=ranged;this.shield=shield;}
    void reserve(Effect kind){
        require(!poisoned||kind==Effect.ABORT||kind==Effect.SHIELD_CLEANUP,"target_effect_scope_poisoned");
        switch(kind){
            case MELEE -> {require(!ranged&&!offenseReserved,"target_single_melee_budget");offenseReserved=true;}
            case DRAW -> {require(ranged&&!drawReserved&&!offenseReserved,"target_single_draw_budget");drawReserved=true;}
            case BOW_RELEASE -> {require(ranged&&drawReserved&&!offenseReserved&&local[Effect.DRAW.ordinal()]==1
                &&packets[Effect.DRAW.ordinal()]==1,"target_single_release_budget");offenseReserved=true;}
            case SHIELD_USE -> {require(shield&&shieldUses<2&&shieldUses==shieldReleases,"target_shield_use_budget");shieldUses++;}
            case SHIELD_RELEASE,SHIELD_CLEANUP -> {require(shield&&shieldReleases<shieldUses,"target_shield_release_budget");shieldReleases++;}
            case ABORT -> {require(ranged&&drawReserved&&!abortReserved,"target_abort_budget");abortReserved=true;}
            case SWING -> require(!ranged&&offenseReserved&&local[Effect.MELEE.ordinal()]==1
                &&packets[Effect.MELEE.ordinal()]==1&&packets[kind.ordinal()]==0,"target_swing_budget");
        }
    }
    void chargeLocal(Effect kind){require(!poisoned||kind==Effect.ABORT||kind==Effect.SHIELD_CLEANUP,"target_effect_scope_poisoned");
        int limit=kind==Effect.SHIELD_USE||kind==Effect.SHIELD_RELEASE||kind==Effect.SHIELD_CLEANUP?2:1;
        require(++local[kind.ordinal()]<=limit,"target_duplicate_local_effect");}
    void chargePacket(Effect kind){require(!poisoned||kind==Effect.ABORT||kind==Effect.SHIELD_CLEANUP,"target_effect_scope_poisoned");
        int limit=kind==Effect.SHIELD_USE||kind==Effect.SHIELD_RELEASE||kind==Effect.SHIELD_CLEANUP?2:1;
        require(++packets[kind.ordinal()]<=limit,"target_duplicate_effect_packet");}
    int local(Effect... kinds){int n=0;for(Effect k:kinds)n+=local[k.ordinal()];return n;}
    int packets(Effect... kinds){int n=0;for(Effect k:kinds)n+=packets[k.ordinal()];return n;}
    boolean attempted(){return offenseReserved||drawReserved||shieldUses>0;}
    boolean unknown(){return poisoned;}
    void poison(){poisoned=true;}
    private void require(boolean ok,String reason){if(!ok){poisoned=true;throw new IllegalStateException(reason);}}
}
