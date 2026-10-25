package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
/** Runs actual native closed request admission and retained pure policies; no Minecraft launch. */
public final class ScopedTargetAdmissionChecks {
    static int checks;
    static void ok(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    static void denied(JsonObject value){boolean failed=false;try{ScopedTargetAction.validateIntent(value);}catch(RuntimeException expected){failed=true;}ok(failed);}
    static JsonObject request(String action,String type){
        JsonObject v=new JsonObject();v.addProperty("action",action);v.addProperty("action_id","offline-one");
        v.addProperty("target_type",type);v.addProperty("target_entity_id",12);v.addProperty("timeout_ms",5000);
        v.addProperty("min_health",12);v.addProperty("expected_hotbar_slot",0);v.addProperty("expected_dimension","minecraft:the_end");
        for(String field:new String[]{"target_uuid","expected_world_generation","expected_player_uuid","expected_action_session"})
            v.addProperty(field,"00000000-0000-0000-0000-000000000001");
        JsonObject held=new JsonObject();held.addProperty("id",action.equals("shoot_entity")?"minecraft:bow":"minecraft:iron_axe");v.add("expected_held_item",held);JsonObject guard=new JsonObject();guard.addProperty("schema_version",1);
        guard.addProperty("source_tick",1);guard.addProperty("source_nano","1");v.add("capability_guard",guard);
        if(action.equals("shoot_entity"))v.addProperty("draw_ticks",20);return v;
    }
    static void snapshotChecks(){
        // Actual production snapshot comparator, with hostile equals/hashCode tokens.
        Object token=new Object(){public boolean equals(Object o){throw new AssertionError("identity reader called equals");}
            public int hashCode(){throw new AssertionError("identity reader called hashCode");}};
        var identities=java.util.Arrays.asList(token,null,new Object());
        var values=java.util.List.of(0L,72000L,0L,Double.doubleToRawLongBits(3.0),100L,1L,0L);
        var baseline=new ScopedTargetAction.PolicyGeometry(identities,values);
        ok(ScopedTargetAction.samePolicyGeometry(baseline,new ScopedTargetAction.PolicyGeometry(identities,values)));
        for(int index=0;index<identities.size();index++){
            var changed=new java.util.ArrayList<Object>(identities);changed.set(index,new Object());
            ok(!ScopedTargetAction.samePolicyGeometry(baseline,new ScopedTargetAction.PolicyGeometry(changed,values)));
        }
        for(int index=0;index<values.size();index++){
            var changed=new java.util.ArrayList<Long>(values);changed.set(index,changed.get(index)+1);
            ok(!ScopedTargetAction.samePolicyGeometry(baseline,new ScopedTargetAction.PolicyGeometry(identities,changed)));
        }
        ok(!ScopedTargetAction.samePolicyGeometry(baseline,new ScopedTargetAction.PolicyGeometry(identities,java.util.List.of())));
        var stack=new ScopedTargetAction.StackGeometry(null,token,1,java.util.List.of(token),java.util.List.of(token));
        var player=new ScopedTargetAction.PlayerGeometry(20,null,true,false,false,false,false,false,false,false,null,stack,true,false);
        var before=new ScopedTargetAction.Geometry(.5,64,.5,0,0,null,null,player,java.util.List.of(),java.util.List.of(stack),java.util.List.of(stack),baseline,java.util.List.of());
        ScopedTargetAction.compareGeometry(before,before);ok(true);
        for(int index=0;index<values.size();index++){
            var changed=new java.util.ArrayList<Long>(values);changed.set(index,changed.get(index)+1);
            var after=new ScopedTargetAction.Geometry(.5,64,.5,0,0,null,null,player,java.util.List.of(),java.util.List.of(stack),java.util.List.of(stack),
                new ScopedTargetAction.PolicyGeometry(identities,changed),java.util.List.of());
            boolean refused=false;try{ScopedTargetAction.compareGeometry(before,after);}catch(RuntimeException expected){refused=true;}ok(refused);
        }
        var changedStack=new ScopedTargetAction.StackGeometry(null,new Object(),1,java.util.List.of(token),java.util.List.of(token));
        var after=new ScopedTargetAction.Geometry(.5,64,.5,0,0,null,null,player,java.util.List.of(),java.util.List.of(stack),java.util.List.of(changedStack),baseline,java.util.List.of());
        boolean refused=false;try{ScopedTargetAction.compareGeometry(before,after);}catch(RuntimeException expected){refused=true;}ok(refused);
        var cells=new java.util.LinkedHashSet<net.minecraft.core.BlockPos>();
        var eye=new net.minecraft.world.phys.Vec3(.5,65.62,.5);
        var end=new net.minecraft.world.phys.Vec3(16.5,66.0,.5);
        ScopedTargetAction.addSegment(cells,eye,end);
        ok(cells.contains(new net.minecraft.core.BlockPos(8,66,0)));
        ok(cells.contains(new net.minecraft.core.BlockPos(8,66,1))); // loaded .6 margin
        ok(cells.size()<512);
        cells.clear();double flat=31,dy=5,elevation=CapabilityTargetPolicy.bowElevation(flat,dy),time=flat/(3*Math.cos(elevation));
        var previous=eye;
        for(int i=1;i<=24;i++){
            double tick=time*i/24,run=3*Math.cos(elevation)*tick;
            var next=new net.minecraft.world.phys.Vec3(eye.x+run,eye.y+3*Math.sin(elevation)*tick-.025*tick*tick,eye.z);
            ScopedTargetAction.addSegment(cells,previous,next);ok(cells.contains(net.minecraft.core.BlockPos.containing(next)));previous=next;
        }
        ok(cells.size()<1024);
    }
    static void packetReaderChecks()throws Exception{
        var type=net.minecraft.network.protocol.game.ServerboundInteractPacket.class;
        var action=type.getDeclaredField("action");var singleton=type.getDeclaredField("ATTACK_ACTION");
        ok(action.trySetAccessible()&&singleton.trySetAccessible());
        var ctor=type.getDeclaredConstructor(int.class,boolean.class,action.getType());ok(ctor.trySetAccessible());
        var packet=(net.minecraft.network.protocol.game.ServerboundInteractPacket)ctor.newInstance(9,false,singleton.get(null));
        ok(ScopedTargetDispatch.AttackPacketReader.ready());ok(ScopedTargetDispatch.AttackPacketReader.attack(packet));
        action.set(packet,null);ok(!ScopedTargetDispatch.AttackPacketReader.attack(packet));
        action.set(packet,singleton.get(null));ok(ScopedTargetDispatch.AttackPacketReader.attack(packet));
    }
    public static void main(String[] args)throws Exception{
        snapshotChecks();packetReaderChecks();
        for(String type:ScopedTargetAction.MELEE){JsonObject v=request("attack_entity",type);
            if(type.endsWith(":enderman"))v.addProperty("enderman_shelter_required",true);
            if(type.endsWith(":ender_dragon"))v.addProperty("expected_dragon_phase",6);
            ScopedTargetAction.validateIntent(v);ok(true);
        }
        for(String type:ScopedTargetAction.RANGED){JsonObject v=request("shoot_entity",type);
            if(type.endsWith(":creeper"))v.addProperty("creeper_safety_required",true);
            if(type.endsWith(":cave_spider"))v.addProperty("poison_guard_required",true);
            if(type.endsWith(":blaze")){v.addProperty("blaze_safety_mode","fire_resistance");v.addProperty("fire_resistance_required",true);}
            ScopedTargetAction.validateIntent(v);ok(true);
        }
        for(int phase=0;phase<11;phase++){JsonObject v=request("attack_entity","minecraft:ender_dragon");v.addProperty("expected_dragon_phase",phase);
            if(phase==6||phase==7){ScopedTargetAction.validateIntent(v);ok(true);}else denied(v);}
        for(String type:new String[]{"minecraft:player","minecraft:creeper","minecraft:end_crystal","minecraft:shulker_bullet"})denied(request("attack_entity",type));
        denied(request("shoot_entity","minecraft:enderman"));denied(request("shoot_entity","minecraft:ender_dragon"));
        for(String flag:new String[]{"hotbar_slot","follow_target","retarget","retry"}){JsonObject v=request("attack_entity","minecraft:zombie");v.addProperty(flag,1);denied(v);}
        for(int ticks:new int[]{0,19,21,40}){JsonObject v=request("shoot_entity","minecraft:zombie");v.addProperty("draw_ticks",ticks);denied(v);}
        for(String key:new String[]{"draw_ticks","timeout_ms","target_entity_id","expected_hotbar_slot"}){JsonObject v=request("shoot_entity","minecraft:zombie");v.addProperty(key,true);denied(v);}
        JsonObject sword=request("attack_entity","minecraft:zombie");sword.getAsJsonObject("expected_held_item").addProperty("id","minecraft:iron_sword");denied(sword);
        JsonObject v=request("shoot_entity","minecraft:end_crystal");v.addProperty("min_health",11.99);denied(v);
        v=request("attack_entity","minecraft:enderman");v.addProperty("enderman_shelter_required",false);denied(v);
        v=request("shoot_entity","minecraft:blaze");v.addProperty("blaze_safety_mode","shield_window");v.add("expected_offhand_item",new JsonObject());v.addProperty("min_health",18);v.addProperty("timeout_ms",20000);ScopedTargetAction.validateIntent(v);ok(true);
        v.addProperty("timeout_ms",17999);denied(v);
        for(double distance:new double[]{Double.NaN,Double.POSITIVE_INFINITY,11.99,32.01})ok(!CapabilityTargetPolicy.crystalClear(distance));
        ok(CapabilityTargetPolicy.crystalClear(12));ok(!CapabilityTargetPolicy.meleeReach(3.01,5));
        ok(Double.isFinite(CapabilityTargetPolicy.bowElevation(16,2)));
        System.out.println("ScopedTargetAdmissionChecks: "+checks+" actual native admission/policy checks passed (no game launch)");
    }
}
