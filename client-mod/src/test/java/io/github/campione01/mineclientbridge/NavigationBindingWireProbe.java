package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;

/** Offline cross-language fixture: real pure snapshot/parse/admission, no Minecraft instance. */
public final class NavigationBindingWireProbe {
    public static void main(String[] args) throws Exception {
        var guard=new PositionDiscontinuityGuard();Object world=new Object(),player=new Object();
        guard.sample(world,player,new PositionDiscontinuityGuard.Sample(.625,64,.7125,0,0,0,true,true,true,false),0);
        for(int tick=1;tick<=3;tick++) guard.sample(world,player,
                new PositionDiscontinuityGuard.Sample(32.625,64,.7125,0,0,0,true,true,true,false),tick);
        JsonObject result=new JsonObject();
        if(args[0].equals("snapshot")) {
            JsonObject state=new JsonObject(),w=new JsonObject(),p=new JsonObject(),a=new JsonObject();
            w.addProperty("world_generation","wire-world");w.addProperty("dimension","minecraft:overworld");
            w.addProperty("game_time",100);w.add("navigation_guard",guard.snapshot());
            p.addProperty("uuid","wire-player");p.addProperty("x",32.625);p.addProperty("y",64);p.addProperty("z",.7125);
            a.addProperty("action_session","wire-session");state.add("world",w);state.add("player",p);state.add("client_action",a);
            result.add("state",state);
        } else {
            JsonObject body=JsonParser.parseString(Files.readString(Path.of(args[1]))).getAsJsonObject();
            try { guard.requireBinding(ClientActionRequest.parse(body).original());result.addProperty("accepted",true); }
            catch(ClientActionRequest.Rejected rejected) {
                result.addProperty("accepted",false);result.addProperty("http_status",rejected.httpStatus);
                result.addProperty("reason",rejected.getMessage());
            }
        }
        System.out.println(result);
    }
}
