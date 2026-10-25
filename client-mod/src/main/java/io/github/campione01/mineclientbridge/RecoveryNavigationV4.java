package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Explicit navigation-only profile. Geometry is a bounded current observation, not a future safety proof. */
final class RecoveryNavigationV4 {
    static final boolean ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryNavigationV4","false"));
    static final int CELL_BOX_LIMIT=16,TOTAL_BOX_LIMIT=512,MAX_RESPONSE_BYTES=65536;
    static String observationProfile(String routeProfile){
        return ENABLED&&RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(routeProfile)?RecoveryShortInputLedger.NAVIGATION_V4_PROFILE:routeProfile;
    }
    /** Only the existing v3 route is dual-profile, and a write must explicitly name its profile. */
    static String bodyProfile(String routeProfile,JsonObject body){
        if(RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(routeProfile)&&body.has("profile")
            &&body.get("profile").isJsonPrimitive()&&body.getAsJsonPrimitive("profile").isString()
            &&RecoveryShortInputLedger.navigationProfile(body.get("profile").getAsString()))return RecoveryShortInputLedger.NAVIGATION_V4_PROFILE;
        return routeProfile;
    }
    static boolean isResponse(JsonObject response){return response.has("profile")&&RecoveryShortInputLedger.navigationProfile(response.get("profile").getAsString());}
    static void checkResponseBudget(JsonObject response){checkResponseBudget(RecoveryShortInputCodec.encode(response));}
    static void checkResponseBudget(byte[] bytes){if(bytes.length>MAX_RESPONSE_BYTES)throw new IllegalArgumentException("navigation_response_too_large");}
    static boolean validStepHeight(double value){return Double.isFinite(value)&&value>=0&&value<=16;}
    static boolean validBox(double x0,double y0,double z0,double x1,double y1,double z1){
        return Double.isFinite(x0)&&Double.isFinite(y0)&&Double.isFinite(z0)&&Double.isFinite(x1)&&Double.isFinite(y1)&&Double.isFinite(z1)
            &&x0>=-16&&y0>=-16&&z0>=-16&&x1<=16&&y1<=16&&z1<=16&&x0<x1&&y0<y1&&z0<z1;
    }
    static final class Geometry {
        private CollisionContext context;
        private Double stepHeight;
        private Boolean sprinting;
        private int total;
        private boolean complete=true;
        Geometry(LocalPlayer player){
            try{context=CollisionContext.of(player);sprinting=player.isSprinting();double value=player.maxUpStep();if(validStepHeight(value))stepHeight=value;else complete=false;}
            catch(RuntimeException failure){complete=false;}
        }
        /** Pure fixture constructor: no actual entity is constructed by offline tests. */
        Geometry(double stepHeight){sprinting=false;if(validStepHeight(stepHeight))this.stepHeight=stepHeight;else complete=false;}
        void unloaded(JsonObject cell){complete=false;cell.add("collision_boxes",JsonNull.INSTANCE);}
        void cell(JsonObject cell,BlockState state,BlockGetter level,BlockPos position){
            try{if(context==null)throw new IllegalArgumentException("missing_collision_context");shape(cell,state.getCollisionShape(level,position,context));}
            catch(RuntimeException failure){failed(cell);}
        }
        void shape(JsonObject cell,VoxelShape shape){
            try{
                JsonArray boxes=new JsonArray();
                // Throw from the bounded consumer; never allocate an unbounded toAabbs list.
                shape.forAllBoxes((x0,y0,z0,x1,y1,z1)->{
                    if(boxes.size()>=CELL_BOX_LIMIT||total+boxes.size()>=TOTAL_BOX_LIMIT||!validBox(x0,y0,z0,x1,y1,z1))throw new IllegalArgumentException("navigation_geometry_limit");
                    JsonArray box=new JsonArray();for(double value:new double[]{x0,y0,z0,x1,y1,z1})box.add(value==0?0:value);boxes.add(box);
                });
                boolean nonempty=!shape.isEmpty();if(nonempty!=(boxes.size()>0))throw new IllegalArgumentException("navigation_geometry_inconsistent");
                total+=boxes.size();cell.addProperty("collision",nonempty);cell.add("collision_boxes",boxes);
            }catch(RuntimeException failure){failed(cell);}
        }
        void failed(JsonObject cell){complete=false;cell.add("collision",JsonNull.INSTANCE);cell.add("collision_boxes",JsonNull.INSTANCE);}
        void describe(JsonObject out,boolean allCells){out.addProperty("collision_boxes_complete",complete&&allCells);out.addProperty("step_height",stepHeight);out.addProperty("sprinting",sprinting);}
        int totalBoxes(){return total;}
    }
    private RecoveryNavigationV4(){}
}
