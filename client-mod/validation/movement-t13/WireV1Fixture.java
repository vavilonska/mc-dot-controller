package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.List;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Synthetic captured facts only. Production emitters, action representation, digest, and HTTP codec are real.
 * Does not instantiate Minecraft, ClientActions, BridgeServer, a level, an entity, or an input owner.
 */
final class WireV1Fixture {
    static final String PROFILE="movement-flat-observed-v2", ACTION="synthetic-observed-movement-wire-01";
    static final String SESSION="synthetic-session", WORLD="synthetic-world-generation";
    static final String PLAYER="00000000-0000-0000-0000-00000000ffff", SERVER="synthetic-integrated-server-instance";
    static final long TICK=100, NANO=1_000_000_000L, ADMITTED=NANO+100_000L;
    static JsonObject point(double x,double y,double z) {
        JsonObject p=new JsonObject();p.addProperty("x",x);p.addProperty("y",y);p.addProperty("z",z);return p;
    }
    static JsonObject guard(long tick,long nano) {
        JsonObject g=new JsonObject();g.addProperty("schema_version",1);g.addProperty("source_tick",tick);
        g.addProperty("source_nano",Long.toString(nano));return g;
    }
    static JsonObject request() {
        JsonObject r=new JsonObject();r.addProperty("version","scoped-native-preflight/1");r.addProperty("profile",PROFILE);
        r.addProperty("owner_id","0123456789abcdef0123456789abcdef");r.addProperty("owner_generation",1);
        r.addProperty("job_id","synthetic_observed_wire");r.addProperty("defense_epoch",0);return r;
    }
    static JsonObject intent() {
        JsonObject j=new JsonObject();j.addProperty("action_id",ACTION);j.addProperty("action","follow_path");
        j.addProperty("timeout_ms",8000);j.addProperty("capability_route",true);
        j.addProperty("expected_world_generation",WORLD);j.addProperty("expected_dimension","minecraft:overworld");
        j.addProperty("expected_player_uuid",PLAYER);j.addProperty("expected_action_session",SESSION);
        j.addProperty("expected_navigation_epoch",0);j.add("expected_origin",point(12.5,64,25.5));
        JsonArray waypoints=new JsonArray();waypoints.add(point(12.5,64,24.5));j.add("waypoints",waypoints);
        j.addProperty("jump",false);j.addProperty("sneak",false);j.addProperty("sprint",false);
        j.add("capability_guard",guard(TICK-1,NANO-100_000_000));return j;
    }
    static JsonObject emptyStack() {
        JsonObject e=new JsonObject();e.addProperty("id","minecraft:air");e.addProperty("count",0);e.addProperty("empty",true);
        e.addProperty("item_fingerprint","00000000-0000-0000-0000-000000000000");
        e.addProperty("component_fingerprint","00000000-0000-0000-0000-000000000001");
        e.addProperty("max_stack_size",64);return e;
    }
    static JsonObject menu() {
        JsonObject m=new JsonObject();m.addProperty("menu_class","net.minecraft.world.inventory.InventoryMenu");
        m.addProperty("state_id",0);m.addProperty("container_id",0);m.add("carried",emptyStack());
        m.addProperty("slots_truncated",false);m.addProperty("slots_total",46);m.addProperty("slots_returned",46);
        JsonArray slots=new JsonArray(),permissions=new JsonArray();
        for(int i=0;i<46;i++) {
            Integer inv=i>=5 && i<=8?Integer.valueOf(44-i):i>=9 && i<=35?Integer.valueOf(i):i>=36 && i<=44?Integer.valueOf(i-36):i==45?Integer.valueOf(40):null;
            JsonObject slot=new JsonObject();slot.addProperty("menu_index",i);slot.addProperty("slot_index",i);
            slot.addProperty("container_slot",inv==null?i:inv);slot.addProperty("active",true);
            slot.addProperty("player_inventory",inv!=null);if(inv!=null)slot.addProperty("inventory_index",inv);
            slot.add("item",emptyStack());slots.add(slot);
            JsonObject permission=new JsonObject();permission.addProperty("may_pickup",true);
            permission.addProperty("may_place_carried",true);permission.addProperty("max_stack_size",64);permissions.add(permission);
        }
        m.add("slots",slots);m.add("slot_permissions",permissions);return m;
    }
    static JsonObject movement(Frame frame) {
        ScopedFlatPolicy.Bounds b=ScopedFlatPolicy.route(12.5,64,25.5,List.of(new ScopedFlatPolicy.Point(12.5,64,24.5)));
        JsonObject m=new JsonObject();m.addProperty("profile",PROFILE);m.addProperty("source","native-client-loaded-level");
        m.addProperty("min_x",b.minX());m.addProperty("max_x",b.maxX());m.addProperty("min_y",b.minY());m.addProperty("max_y",b.maxY());
        m.addProperty("min_z",b.minZ());m.addProperty("max_z",b.maxZ());m.addProperty("feet_y",b.feetY());
        m.addProperty("steps",b.steps());m.addProperty("halo",ScopedFlatPolicy.HALO);m.addProperty("expected_cells",b.cells());
        m.addProperty("all_loaded",true);m.addProperty("closed_inventory",true);m.addProperty("survival",true);m.addProperty("using_item",false);
        m.addProperty("maximum_horizontal_speed",ScopedFlatPolicy.MAX_SPEED);
        m.addProperty("maximum_tick_sampled_displacement",ScopedFlatPolicy.MAX_TICK_DISPLACEMENT);
        m.addProperty("deadline_nano",Long.toString(NANO+8_000_000_000L));
        JsonArray cells=new JsonArray();
        for(int x=b.minX();x<=b.maxX();x++)for(int y=b.minY();y<=b.maxY();y++)for(int z=b.minZ();z<=b.maxZ();z++) {
            boolean floor=y==b.feetY()-1;JsonObject cell=new JsonObject();
            cell.addProperty("x",x);cell.addProperty("y",y);cell.addProperty("z",z);
            cell.addProperty("id",floor?"minecraft:stone":"minecraft:air");
            cell.addProperty("state",floor?"Block{minecraft:stone}":"Block{minecraft:air}");
            cell.addProperty("fluid","minecraft:empty");cell.addProperty("full_cube",floor);cell.addProperty("friction",floor?0.6d:0d);cells.add(cell);
        }
        m.add("cells",cells);m.add("entity_guard",frame.json());return m;
    }
    static JsonObject facts(Frame frame) {
        JsonObject f=new JsonObject(),c=new JsonObject();c.addProperty("world_generation",WORLD);c.addProperty("dimension","minecraft:overworld");
        c.addProperty("player_uuid",PLAYER);c.addProperty("action_session",SESSION);c.addProperty("integrated_server_instance",SERVER);f.add("context",c);
        f.addProperty("private_singleplayer",true);f.addProperty("focused",true);f.addProperty("paused",false);
        f.addProperty("alive",true);f.addProperty("spectator",false);f.addProperty("health",20.0);f.addProperty("hurt_time",0);
        f.addProperty("x",12.5);f.addProperty("y",64.0);f.addProperty("z",25.5);f.addProperty("selected_slot",0);f.addProperty("screen_class","");
        for(String k:List.of("on_fire","in_water","in_lava","powder_snow","using_item"))f.addProperty(k,false);
        f.addProperty("food_level",20);f.addProperty("food_saturation",5.0);JsonObject held=new JsonObject();held.addProperty("neutral",true);f.add("held_inputs",held);
        JsonArray inventory=new JsonArray();for(int i=0;i<41;i++){JsonObject row=new JsonObject();row.addProperty("slot",i);row.add("item",emptyStack());inventory.add(row);}
        f.add("inventory",inventory);f.addProperty("inventory_total",41);JsonObject equipment=new JsonObject();
        for(String k:List.of("mainhand","offhand","feet","legs","chest","head"))equipment.add(k,emptyStack());f.add("equipment",equipment);
        f.add("effects",new JsonArray());f.add("menu",menu());f.add("movement",movement(frame));return f;
    }
    static Frame entities(List<Row> rows) { return frame(TICK,NANO+50_000,160,1,WireV1Facts.PRISM,rows); }
    static Frame entities() {
        return entities(List.of(WireV1Facts.far(10,"minecraft:sheep"),WireV1Facts.far(20,"minecraft:boat"),WireV1Facts.removed(30)));
    }
    static JsonObject witness(Frame frame) {
        return witness(frame,intent(),facts(frame));
    }
    static JsonObject witness(Frame frame,JsonObject intent,JsonObject facts) {
        JsonObject compiled=intent.deepCopy();compiled.add("capability_guard",guard(TICK,NANO));
        return ScopedNativePreflight.serializeWitness(request(),ACTION,SESSION,7,SERVER,
            ScopedNativePreflight.digest(intent),ScopedNativePreflight.digest(compiled),TICK,NANO,ADMITTED,facts,intent.getAsJsonObject("capability_guard"));
    }
    static JsonObject action(Frame frame) {
        return action(frame,intent(),facts(frame));
    }
    static JsonObject action(Frame frame,JsonObject intent,JsonObject facts) {
        JsonObject compiled=intent.deepCopy();compiled.add("capability_guard",guard(TICK,NANO));
        ClientActionRequest request=new ClientActionRequest(ACTION,"follow_path",8000,
            List.of(new ClientActionRequest.Point(12.5,64,24.5,false)),null,null,null,-1,false,false,-1,-1,0,null,compiled);
        ActionRegistry.Entry entry=new ActionRegistry.Entry(request);entry.result.add("scoped_native_preflight",witness(frame,intent,facts));
        entry.result.addProperty("world_generation",WORLD);JsonObject action=entry.json(true);action.addProperty("action_session",SESSION);
        JsonObject budget=new JsonObject();budget.addProperty("active",false);budget.add("reason",JsonNull.INSTANCE);action.add("movement_budget",budget);
        return action;
    }
    static JsonObject protocol(JsonObject body) {
        JsonObject j=body.deepCopy();j.addProperty("ok",true);j.addProperty("protocol","mineclient-bridge");j.addProperty("schema_version",2);return j;
    }
    static JsonObject actionEndpoint(JsonObject action,boolean start) {
        try { return BridgeServer.ActionResponses.result(()->action.deepCopy(),start).body(); }
        catch(Exception failed) { throw new AssertionError("Pure production action wrapper failed",failed); }
    }
    static JsonObject capability(JsonObject action) {
        Object level=new Object(),playerIdentity=new Object(),gameMode=new Object(),menuIdentity=new Object();
        CapabilitySnapshot.Context context=new CapabilitySnapshot.Context(level,playerIdentity,gameMode,null,menuIdentity,WORLD,PLAYER,"minecraft:overworld",SESSION,TICK);
        JsonObject world=new JsonObject();world.addProperty("present",true);world.addProperty("world_generation",WORLD);
        world.addProperty("dimension","minecraft:overworld");world.addProperty("game_time",TICK);
        JsonObject player=point(12.5,64,25.5);player.addProperty("present",true);player.addProperty("uuid",PLAYER);
        player.addProperty("alive",true);player.addProperty("health",20.0);
        player.addProperty("dimension","minecraft:overworld");player.addProperty("yaw",180.0);player.addProperty("pitch",0.0);
        JsonObject status=protocol(new JsonObject());status.addProperty("in_world",true);status.addProperty("run_id","synthetic-run");status.addProperty("process_id",1);
        status.add("world",world.deepCopy());status.add("player",player.deepCopy());status.add("client_action",action.deepCopy());
        JsonObject statusScreen=new JsonObject();statusScreen.addProperty("present",false);status.add("screen",statusScreen);
        JsonObject state=protocol(new JsonObject());state.add("world",world.deepCopy());state.add("player",player.deepCopy());
        state.add("client_action",action.deepCopy());state.add("movement_budget",action.get("movement_budget").deepCopy());
        state.add("capability_guard",guard(TICK,NANO));state.add("menu",menu());state.addProperty("screen_open",false);
        JsonObject held=new JsonObject();held.addProperty("neutral",true);state.add("held_inputs",held);
        state.addProperty("paused",false);state.addProperty("focused",true);state.addProperty("private_singleplayer",true);
        JsonObject nearby=new JsonObject();nearby.addProperty("radius",8.0);nearby.addProperty("returned",0);nearby.addProperty("total",0);
        nearby.addProperty("truncated",false);nearby.add("entities",new JsonArray());state.add("nearby",nearby);
        JsonObject screen=protocol(new JsonObject());screen.addProperty("open",false);screen.add("menu",menu());
        return CapabilitySnapshot.assemble(context,context,status,action,state,screen,action);
    }
    private WireV1Fixture() { }
}
