package io.github.campione01.mineclientbridge;

import java.io.*;
import java.util.Set;

/** V3 observation lease metadata only; never changes a request deadline or authorizes an effect. */
final class RecoveryChallengeLease {
    static final long V3_MAX_NANOS=1_000_000_000L,V3_MAX_TICKS=20;
    static final long V5_MAX_NANOS=2_000_000_000L,V5_MAX_TICKS=40;
    record Refusal(String stage,Long ageNs,Long tickDelta,int predicateMask,boolean maintenanceWindow) {
        Refusal(String stage,Long ageNs,Long tickDelta,int predicateMask){this(stage,ageNs,tickDelta,predicateMask,false);}
        Refusal {
            if(!Set.of("observe","admit","first_interaction_tick","first_input").contains(stage))throw new IllegalArgumentException("invalid_refusal_stage");
            if(predicateMask==-1||predicateMask==-2){
                if(!stage.equals("admit")||ageNs!=null||tickDelta!=null)throw new IllegalArgumentException("invalid_missing_observation_refusal");
            }else if(ageNs==null||tickDelta==null||!Set.of(0,1,3,7,15,31,63,127).contains(predicateMask))throw new IllegalArgumentException("invalid_refusal_predicates");
            else if(windowMask(ageNs,tickDelta,maintenanceWindow)!=(predicateMask<15?predicateMask:15))throw new IllegalArgumentException("inconsistent_refusal_predicates");
        }
    }
    static int windowMask(long age,long ticks){
        if(age<0)return 0;if(age>V3_MAX_NANOS)return 1;if(ticks<0)return 3;if(ticks>V3_MAX_TICKS)return 7;return 15;
    }
    static int windowMask(long age,long ticks,boolean maintenance){
        if(!maintenance)return windowMask(age,ticks);
        if(age<0)return 0;if(age>V5_MAX_NANOS)return 1;if(ticks<0)return 3;if(ticks>V5_MAX_TICKS)return 7;return 15;
    }
    static void write(DataOutputStream out,Refusal refusal)throws IOException {
        out.writeBoolean(refusal!=null);if(refusal==null)return;
        if(refusal.stage().equals("observe"))throw new IOException("observation_only_refusal");
        out.writeUTF(refusal.stage());out.writeBoolean(refusal.ageNs()!=null);
        if(refusal.ageNs()!=null){out.writeLong(refusal.ageNs());out.writeLong(refusal.tickDelta());}out.writeInt(refusal.predicateMask());
    }
    static Refusal read(DataInputStream in)throws IOException {
        if(!in.readBoolean())return null;String stage=in.readUTF();boolean numbers=in.readBoolean();
        Long age=numbers?in.readLong():null,delta=numbers?in.readLong():null;int mask=in.readInt();
        try{var value=new Refusal(stage,age,delta,mask);if(stage.equals("observe"))throw new IllegalArgumentException("observation_only_refusal");return value;}
        catch(IllegalArgumentException invalid){throw new IOException("invalid_observation_refusal",invalid);}
    }
    /** Same wire bytes; the already-decoded request profile selects diagnostic consistency limits. */
    static Refusal read(DataInputStream in,boolean maintenance)throws IOException {
        if(!maintenance)return read(in);
        if(!in.readBoolean())return null;String stage=in.readUTF();boolean numbers=in.readBoolean();
        Long age=numbers?in.readLong():null,delta=numbers?in.readLong():null;int mask=in.readInt();
        try{var value=new Refusal(stage,age,delta,mask,true);if(stage.equals("observe"))throw new IllegalArgumentException("observation_only_refusal");return value;}
        catch(IllegalArgumentException invalid){throw new IOException("invalid_observation_refusal",invalid);}
    }
    private RecoveryChallengeLease(){}
}
