package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.List;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.entity.vehicle.Boat;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.shapes.CollisionContext;

/** Phase one: already aboard an ordinary boat, loaded still-water route, remain aboard. */
final class BoundedBoatDrive {
    record Step(boolean left,boolean right,boolean up,boolean down,String terminal,String reason) { }
    final BoatDriveRequest request;
    final Boat boat;
    final net.minecraft.client.player.LocalPlayer player;
    final BoatDriveGuard.Identity identity;
    final JsonObject evidence;
    final BoatSteering.Point start;
    int waypoint, settledTicks, stagnantTicks, turnLock;
    double lastProgressX,lastProgressZ;
    double clearanceHalfX,clearanceHalfZ,clearanceMinY,clearanceMaxY;
    boolean settled;
    BoundedBoatDrive(Minecraft mc,BoatDriveRequest request,JsonObject evidence) {
        this.request=request;this.evidence=evidence;this.player=mc.player;
        if(!(mc.player.getVehicle() instanceof Boat actual))throw rejected("requires_mounted_boat");
        boat=actual;
        start=new BoatSteering.Point(boat.getX(),boat.getZ());
        identity=new BoatDriveGuard.Identity(request.world(),request.player(),request.session(),request.vehicle(),request.vehicleId(),passengers());
        String reason=guard(mc);if(reason!=null)throw rejected(reason);
        double x=boat.getX(),z=boat.getZ(),length=0;
        for(var point:request.points()) {
            double dx=point.x()-x,dz=point.z()-z,d=Math.hypot(dx,dz);
            if(d>BoatDriveRequest.MAX_SEGMENT)throw rejected("boat_segment_025_to_16");
            length+=d;if(length>BoatDriveRequest.MAX_LENGTH)throw rejected("boat_route_too_long");
            var check=corridor(mc,x,z,dx,dz,.2);
            if(!check.clear())throw rejected("boat_route_"+check.reason());
            x=point.x();z=point.z();
        }
        lastProgressX=boat.getX();lastProgressZ=boat.getZ();
        evidence.addProperty("boat_schema_version",1);evidence.addProperty("route_length",length);
        evidence.addProperty("waypoint_count",request.points().size());evidence.addProperty("dynamic_append_supported",false);
        evidence.addProperty("boat_settled",false);evidence.addProperty("input_released",false);
    }
    Step tick(Minecraft mc) {
        settled=false;
        evidence.add("vehicle",BoatObservation.snapshot(mc));
        String reason=guard(mc);if(reason!=null)return stop(reason);
        var previous=waypoint==0?start:request.points().get(waypoint-1);
        if(BoatCollision.distanceToSegment(boat.getX(),boat.getZ(),previous,request.points().get(waypoint))>2.5)
            return stop("boat_route_deviation");
        var v=boat.getDeltaMovement();
        var pose=new BoatSteering.Pose(boat.getX(),boat.getZ(),boat.getYRot(),v.x,v.z,boat.deltaRotation);
        var decision=BoatSteering.decide(pose,request.points(),waypoint,turnLock);
        var step=decision.step();waypoint=step.waypoint();turnLock=decision.turnLock();
        evidence.addProperty("turn_lock",turnLock);
        evidence.addProperty("waypoint_index",waypoint);evidence.addProperty("distance_to_waypoint",step.distance());
        evidence.addProperty("phase",step.phase());evidence.addProperty("safety_distance",BoatSteering.safetyDistance(pose.speed()));
        // One current collision/fluid read, then BOTH momentum and intended travel
        // corridors. No coarse grid, cached safety flag, chunk request, or model tick.
        double horizon=BoatSteering.safetyDistance(pose.speed());
        double dx=pose.speed()<1e-7?0:v.x/pose.speed()*horizon;
        double dz=pose.speed()<1e-7?0:v.z/pose.speed()*horizon;
        var check=corridor(mc,boat.getX(),boat.getZ(),dx,dz,1.0);
        if(!check.clear())return unsafe(check);
        if(step.forward()||step.left()||step.right()) {
            double yaw=Math.toRadians(boat.getYRot());
            var heading=corridor(mc,boat.getX(),boat.getZ(),-Math.sin(yaw)*horizon,Math.cos(yaw)*horizon,1.0);
            if(!heading.clear())return unsafe(heading);
            String risk=entityRisk(mc,-Math.sin(yaw)*horizon,Math.cos(yaw)*horizon);
            if(risk!=null)return stop(risk);
        }
        String obstacle=entityRisk(mc,dx,dz);if(obstacle!=null)return stop(obstacle);
        if(step.settled())settledTicks++;else settledTicks=0;
        settled=settledTicks>=4;
        evidence.addProperty("settled_ticks",settledTicks);evidence.addProperty("boat_settled",settled);
        if(settled)return new Step(false,false,false,false,"succeeded","boat_settled_at_endpoint");
        if(Math.hypot(boat.getX()-lastProgressX,boat.getZ()-lastProgressZ)>.1) {
            lastProgressX=boat.getX();lastProgressZ=boat.getZ();stagnantTicks=0;
        } else if(++stagnantTicks>=200)return stop("boat_no_progress");
        evidence.addProperty("requested_left",step.left());evidence.addProperty("requested_right",step.right());
        evidence.addProperty("requested_forward",step.forward());evidence.addProperty("requested_backward",step.backward());
        return new Step(step.left(),step.right(),step.forward(),step.backward(),null,step.phase());
    }
    private String guard(Minecraft mc) {
        if(mc.player==null||mc.level==null||mc.player.getVehicle()!=boat)return "vehicle_changed";
        var observed=new BoatDriveGuard.Identity(WorldGeneration.current(mc.level),mc.player.getUUID().toString(),
                ClientActions.session(),boat.getUUID().toString(),boat.getId(),passengers());
        var v=boat.getDeltaMovement();
        String reason=BoatDriveGuard.reject(identity,new BoatDriveGuard.Sample(observed,boat.getControllingPassenger()==mc.player,
                boat.getClass()==Boat.class,boat.status==Boat.Status.IN_WATER,boat.isAboveBubbleColumn,
                boat.isAlive()&&!boat.isRemoved(),boat.horizontalCollision, v.horizontalDistance(),v.y,boat.getY(),request.surfaceY()));
        if(reason!=null)return reason;
        return passengerClearance();
    }
    private String passengerClearance() {
        try {
            var hull=boat.getBoundingBox();
            if(!BoatPassengerEnvelope.valid(box(hull))||!Float.isFinite(boat.getYRot())
                    ||hull.getXsize()>1.5||hull.getZsize()>1.5||hull.getYsize()>.7)
                return "unsupported_boat_dimensions";
            var riders=boat.getPassengers();
            long uniqueCount=riders.stream().map(Entity::getUUID).distinct().count();
            if(BoatPassengerEnvelope.membership(riders.size(),uniqueCount,true,true,false,0)!=null)
                return "unsupported_passengers";
            clearanceHalfX=hull.getXsize()/2;clearanceHalfZ=hull.getZsize()/2;
            clearanceMinY=hull.minY;clearanceMaxY=hull.maxY;
            for(var passenger:riders) {
                String membershipReason=BoatPassengerEnvelope.membership(riders.size(),uniqueCount,
                        passenger.getVehicle()==boat,passenger.isAlive()&&!passenger.isRemoved(),
                        passenger.isSpectator(),passenger.getPassengers().size());
                if(membershipReason!=null)return membershipReason;
                var actual=passenger.getBoundingBox();
                var attachment=passenger.getVehicleAttachmentPoint(boat);
                String attachmentReason=BoatPassengerEnvelope.attachment(attachment.x,attachment.y,attachment.z);
                if(attachmentReason!=null)return attachmentReason;
                var mount=boat.getPassengerRidingPosition(passenger).subtract(attachment);
                var expected=passenger.getDimensions(passenger.getPose()).makeBoundingBox(mount);
                var envelope=BoatPassengerEnvelope.inspect(box(actual),box(expected),boat.getX(),boat.getZ(),request.surfaceY());
                if(!envelope.accepted())return envelope.reason();
                clearanceHalfX=Math.max(clearanceHalfX,envelope.radius());
                clearanceHalfZ=Math.max(clearanceHalfZ,envelope.radius());
                clearanceMinY=Math.min(clearanceMinY,actual.minY);clearanceMaxY=Math.max(clearanceMaxY,actual.maxY);
            }
            evidence.addProperty("passenger_clearance_schema_version",1);
            evidence.addProperty("clearance_half_x",clearanceHalfX);evidence.addProperty("clearance_half_z",clearanceHalfZ);
            evidence.addProperty("clearance_min_y",clearanceMinY);evidence.addProperty("clearance_max_y",clearanceMaxY);
            return null;
        } catch(RuntimeException unknown) {return "passenger_geometry_unknown";}
    }

    private List<String> passengers() {return boat.getPassengers().stream().map(p->p.getUUID().toString()).toList();}
    private BoatCorridor.Result corridor(Minecraft mc,double x,double z,double dx,double dz,double margin) {
        var context=CollisionContext.of(boat);
        return BoatCorridor.check(x,z,dx,dz,clearanceHalfX+margin,clearanceHalfZ+margin,request.surfaceY(),(bx,by,bz)->{
            BlockPos pos=new BlockPos(bx,by,bz);
            if(mc.level.isOutsideBuildHeight(pos)||!mc.level.getWorldBorder().isWithinBounds(pos)||!mc.level.hasChunkAt(pos))
                return new BoatCorridor.Cell(false,false,false,false,false,false);
            var state=mc.level.getBlockState(pos);var fluid=state.getFluidState();
            boolean empty=state.getCollisionShape(mc.level,pos,context).isEmpty();
            return new BoatCorridor.Cell(true,true,empty,state.is(Blocks.WATER)&&fluid.isSource(),state.isAir(),
                    state.is(Blocks.BUBBLE_COLUMN)||state.is(Blocks.MAGMA_BLOCK)||state.is(Blocks.SOUL_SAND)||state.is(Blocks.LAVA));
        });
    }
    private String entityRisk(Minecraft mc,double dx,double dz) {
        // Broad-phase conservative union; moving entities get a bounded predicted
        // envelope. All non-passengers are protected, even passive mobs/items.
        AABB body=boat.getBoundingBox().inflate(0,2,0).minmax(new AABB(
                boat.getX()-clearanceHalfX,clearanceMinY,boat.getZ()-clearanceHalfZ,
                boat.getX()+clearanceHalfX,clearanceMaxY,boat.getZ()+clearanceHalfZ));
        AABB hull=body.expandTowards(dx,0,dz).inflate(1.2,0,1.2);
        for(Entity e:mc.level.getEntities(boat,hull.inflate(24))) {
            if(e.isRemoved()||e==mc.player||boat.getPassengers().contains(e))continue;
            if((e instanceof Enemy||e instanceof Projectile)&&e.distanceToSqr(boat)<144)return "boat_nearby_threat";
            var v=e.getDeltaMovement();
            if(!Double.isFinite(v.x)||!Double.isFinite(v.y)||!Double.isFinite(v.z)||v.horizontalDistance()>1||Math.abs(v.y)>1)return "boat_entity_motion_unknown";
            if(BoatCollision.protectedOverlap(box(body),dx,dz,
                    box(e.getBoundingBox()),v.x,v.y,v.z))return "boat_entity_corridor_blocked";
        }
        return null;
    }
    private static BoatCollision.Box box(AABB b) {return new BoatCollision.Box(b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ);}
    private Step unsafe(BoatCorridor.Result check) {
        evidence.addProperty("unsafe_x",check.x());evidence.addProperty("unsafe_y",check.y());evidence.addProperty("unsafe_z",check.z());
        return stop("boat_safety_"+check.reason());
    }
    private Step stop(String reason) {return new Step(false,false,false,false,"failed",reason);}
    void release(Minecraft mc) {
        // Cancellation releases immediately; braking is ONLY part of normal arrival.
        BoatInputRelease.clear(boat::setInput,(left,right,up,down)-> {
            var input=player.input;input.forwardImpulse=input.leftImpulse=0;
            input.left=left;input.right=right;input.up=up;input.down=down;
            input.jumping=input.shiftKeyDown=false;
        });
        evidence.addProperty("input_released",true);evidence.addProperty("boat_settled",settled);
    }
    private static ClientActionRequest.Rejected rejected(String reason) {return new ClientActionRequest.Rejected(409,reason);}
}
