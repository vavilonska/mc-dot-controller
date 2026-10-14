package io.github.campione01.mineclientbridge;
import java.util.List;
/** Standalone finite policy fixtures. These do not instantiate a client or prove live pickup. */
public final class ScopedCollectPolicyFiniteTest {
    static int checks;
    static final String U="00000000-0000-0000-0000-000000000001", V="00000000-0000-0000-0000-000000000002";
    static final ScopedEntityPolicy.Box PRISM=new ScopedEntityPolicy.Box(-2,63,-2,4,68,3);
    static ScopedEntityPolicy.Row row(int id,String uuid,String type,double speed) {
        var p=new ScopedEntityPolicy.V(1.5,64,.5);var b=new ScopedEntityPolicy.Box(1.375,64,.375,1.625,64.25,.625);
        var v=new ScopedEntityPolicy.V(speed,0,0);
        var f=new ScopedEntityPolicy.Flags(!type.equals("minecraft:item"),true,false,false,false,false,false,false,0,0,null);
        return new ScopedEntityPolicy.Row(id,uuid,type,ScopedEntityPolicy.CLASSES.get(type),false,p,b,v,p,f,ScopedEntityPolicy.project(b,p,v,p,160));
    }
    static void reject(Runnable r,String reason) {
        try{r.run();throw new AssertionError("accepted "+reason);}catch(IllegalArgumentException e){if(!reason.equals(e.getMessage()))throw new AssertionError(e);}
        checks++;
    }
    public static void main(String[] args){
        var item=row(1,U,"minecraft:item",0);
        var admitted=new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(item),U).json();
        if(!admitted.get("permitted_pickup_uuid").getAsString().equals(U)
                || !admitted.getAsJsonArray("rows").get(0).getAsJsonObject().get("verdict").getAsString().equals("pickup_target"))throw new AssertionError();checks++;
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(item)),"scoped_movement_entity_projected_corridor_conflict");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(),U),"scoped_collect_target_row_invalid");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(row(1,V,"minecraft:item",0)),U),"scoped_collect_target_row_invalid");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(row(1,U,"minecraft:cow",0)),U),"scoped_collect_target_row_invalid");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(row(1,U,"minecraft:item",.01)),U),"scoped_collect_target_row_invalid");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(item,row(2,V,"minecraft:item",0)),U),"scoped_movement_entity_projected_corridor_conflict");
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(item,row(2,V,"minecraft:cow",0)),U),"scoped_movement_entity_projected_corridor_conflict");
        var removed=new ScopedEntityPolicy.Row(1,U,"minecraft:item",ScopedEntityPolicy.CLASSES.get("minecraft:item"),true,null,null,null,null,null,null);
        reject(()->new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(removed),U),"scoped_collect_target_row_invalid");
        var ordinary=new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of()).json();if(ordinary.has("permitted_pickup_uuid"))throw new AssertionError();checks++;
        // Actual mapped ItemEntity.tick: gravity -.04 every tick, move every fourth low-speed grounded tick,
        // exact ordinary Block.updateEntityAfterFallOn resets Y before .98 vertical damping.
        double vy=0,vx=.0029,x=1.5;var anchor=new ScopedEntityPolicy.V(x,64,.5);
        for(int tick=1;tick<=160;tick++) {
            vy-=.04;
            if(tick%4==0){x+=vx;vy=0;vx*=.6F*.98F;vy*=.98;}
            var velocity=new ScopedEntityPolicy.V(vx,vy,0);var position=new ScopedEntityPolicy.V(x,64,.5);
            if(!ScopedEntityPolicy.restingPickupMotion(velocity) || !ScopedEntityPolicy.restingPickupAnchor(anchor,position))throw new AssertionError("resting cycle "+tick);checks++;
            var box=new ScopedEntityPolicy.Box(x-.125,64,.375,x+.125,64.25,.625);
            var cycle=new ScopedEntityPolicy.Row(1,U,"minecraft:item",ScopedEntityPolicy.CLASSES.get("minecraft:item"),false,
                    position,box,velocity,position,item.flags(),ScopedEntityPolicy.project(box,position,velocity,position,160));
            new ScopedEntityPolicy.Frame(1,1,160,1,PRISM,List.of(cycle),U).json();checks++;
        }
        for(var velocity:List.of(new ScopedEntityPolicy.V(0,.001,0),new ScopedEntityPolicy.V(0,-.120000002,0),
                new ScopedEntityPolicy.V(.00301,0,0),new ScopedEntityPolicy.V(.003,0,.003))) {
            if(ScopedEntityPolicy.restingPickupMotion(velocity))throw new AssertionError("moving target accepted");checks++;
        }
        for(var position:List.of(new ScopedEntityPolicy.V(1.531,64,.5),new ScopedEntityPolicy.V(1.5,64.031,.5),
                new ScopedEntityPolicy.V(1.5,64,.531),new ScopedEntityPolicy.V(1.5,63.999,.5))) {
            if(ScopedEntityPolicy.restingPickupAnchor(anchor,position))throw new AssertionError("anchor escape accepted");checks++;
        }
        System.out.println("ScopedCollectPolicyFiniteTest passed "+checks+" checks; no game execution");
    }
}
