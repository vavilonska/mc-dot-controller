package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.monster.Creeper;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.core.registries.BuiltInRegistries;

/** Read-only client-tick observer. Never owns inputs, loads chunks or waits for HTTP/server work. */
final class NativeThreatObservation {
    static final int NEAR_LIMIT=128,FAR_LIMIT=128;
    record Contact(int id,String uuid,String type,double x,double y,double z,double distance,
                   boolean creeper,boolean ignited,boolean powered,int swell,int fuse,int direction) {
        boolean imminent(){return creeper && distance<=8 && (ignited||direction>0||distance<3);}
        JsonObject json(){var j=new JsonObject();j.addProperty("entity_id",id);j.addProperty("uuid",uuid);j.addProperty("type",type);
            j.addProperty("x",x);j.addProperty("y",y);j.addProperty("z",z);j.addProperty("distance",distance);
            if(creeper){j.addProperty("ignited",ignited);j.addProperty("powered",powered);j.addProperty("client_swell_ticks",swell);
                j.addProperty("client_fuse_ticks",fuse);j.addProperty("swell_direction",direction);j.addProperty("fuse_source","client_observed_not_server_countdown");}return j;}
    }
    record Frame(Object level,Object player,ObservationClientClock.Stamp clock,long nano,List<Contact> contacts,
                 boolean truncated,int total) { }
    private static Frame near,far;
    private static String unavailable="not_sampled";
    private static long failures;
    static void tick(Minecraft mc){
        try {
            if(mc.level==null||mc.player==null||mc.getSingleplayerServer()==null||mc.getSingleplayerServer().isPublished()) {clear("context_unavailable");return;}
            var clock=ObservationClockBridge.sample();
            if(near!=null&&!clock.sameDomain(near.clock()))clear("context_changed");
            near=scan(mc,clock,16,NEAR_LIMIT);
            if(far==null||!clock.sameDomain(far.clock())||clock.count()-far.clock().count()>=4)far=scan(mc,clock,64,FAR_LIMIT);
            unavailable=null;
        }catch(RuntimeException invalid){failures++;clear("observation_unavailable");}
    }
    private static Frame scan(Minecraft mc,ObservationClientClock.Stamp clock,double radius,int limit){
        var candidates=mc.level.getEntitiesOfClass(Entity.class,mc.player.getBoundingBox().inflate(radius),
            e->e!=mc.player&&!e.isRemoved()&&(e instanceof Enemy||e instanceof Projectile));
        candidates.sort(Comparator.comparingDouble(e->e.distanceToSqr(mc.player)));
        var rows=new ArrayList<Contact>();
        for(Entity e:candidates){if(rows.size()>=limit)break;Creeper c=e instanceof Creeper value?value:null;
            rows.add(new Contact(e.getId(),e.getUUID().toString(),BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString(),
                e.getX(),e.getY(),e.getZ(),Math.sqrt(e.distanceToSqr(mc.player)),c!=null,c!=null&&c.isIgnited(),c!=null&&c.isPowered(),
                c==null?-1:c.swell,c==null?-1:c.maxSwell,c==null?0:c.getSwellDir()));}
        return new Frame(mc.level,mc.player,clock,System.nanoTime(),List.copyOf(rows),candidates.size()>limit,candidates.size());
    }
    static void clear(String reason){near=far=null;unavailable=reason;}
    static Contact creeper(Minecraft mc){Frame f=near;if(f==null||f.level()!=mc.level||f.player()!=mc.player||System.nanoTime()-f.nano()>250_000_000L)return null;
        for(Contact c:f.contacts())if(c.imminent()) {
            Entity e=mc.level.getEntity(c.id());
            if(e instanceof Creeper && e.getUUID().toString().equals(c.uuid()) && e.isAlive()
                    && (c.ignited()||c.direction()>0||mc.player.hasLineOfSight(e)))return c;
        }return null;
    }
    static JsonObject snapshot(){var j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("read_only",true);
        j.addProperty("available",near!=null);j.addProperty("reason",unavailable);j.addProperty("failed_samples",failures);
        j.add("near",json(near,16,1));j.add("far",json(far,64,4));return j;}
    private static JsonObject json(Frame f,int radius,int cadence){var j=new JsonObject();j.addProperty("bbox_inflate",radius);j.addProperty("cadence_client_ticks",cadence);
        j.addProperty("available",f!=null);if(f==null)return j;j.add("source_clock",f.clock().json());j.addProperty("source_nano",Long.toString(f.nano()));
        j.addProperty("age_ns",Math.max(0,System.nanoTime()-f.nano()));j.addProperty("truncated",f.truncated());j.addProperty("total",f.total());
        var a=new JsonArray();for(Contact c:f.contacts()){if(a.size()>=8)break;a.add(c.json());}j.add("contacts",a);j.addProperty("status_returned",a.size());j.addProperty("status_truncated",f.contacts().size()>a.size());return j;}
}
