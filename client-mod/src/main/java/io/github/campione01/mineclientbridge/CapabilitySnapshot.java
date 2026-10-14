package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Validates one client-thread observation. Never repairs or re-stamps a sibling. */
final class CapabilitySnapshot {
    record Context(Object level,Object player,Object gameMode,Object screen,Object menu,
                   String worldGeneration,String playerUuid,String dimension,String actionSession,long tick) {
        boolean same(Context other) {
            return other!=null && level==other.level && player==other.player && gameMode==other.gameMode
                    && screen==other.screen && menu==other.menu && tick==other.tick
                    && worldGeneration.equals(other.worldGeneration) && playerUuid.equals(other.playerUuid)
                    && dimension.equals(other.dimension) && actionSession.equals(other.actionSession);
        }
    }

    static JsonObject assemble(Context before,Context after,JsonObject status,JsonObject action,
                               JsonObject state,JsonObject screen,JsonObject currentAction) {
        if(before==null || before.level==null || before.player==null || before.gameMode==null
                || !before.same(after)) throw new ClientActionRequest.Rejected(409,"capability_snapshot_context_changed");
        try {
            for(JsonObject sibling:new JsonObject[]{status,state,screen})
                require(sibling.get("ok").getAsBoolean() && sibling.get("protocol").getAsString().equals("mineclient-bridge")
                        && sibling.get("schema_version").getAsInt()==2);
            require(status.get("in_world").getAsBoolean());
            for(JsonObject sibling:new JsonObject[]{status,state}) {
                JsonObject world=sibling.getAsJsonObject("world"),player=sibling.getAsJsonObject("player");
                require(world.get("world_generation").getAsString().equals(before.worldGeneration)
                        && world.get("dimension").getAsString().equals(before.dimension)
                        && world.get("game_time").getAsLong()==before.tick
                        && player.get("uuid").getAsString().equals(before.playerUuid));
                require(sibling.getAsJsonObject("client_action").equals(action));
            }
            for(String field:new String[]{"x","y","z","yaw","pitch"})
                require(status.getAsJsonObject("player").get(field).equals(state.getAsJsonObject("player").get(field)));
            require(action.equals(currentAction) && action.get("ok").getAsBoolean()
                    && action.get("action_session").getAsString().equals(before.actionSession));
            require(state.getAsJsonObject("player").get("dimension").getAsString().equals(before.dimension));
            JsonObject guard=state.getAsJsonObject("capability_guard");
            require(guard.get("schema_version").getAsInt()==1 && guard.get("source_tick").getAsLong()==before.tick);
            // Parse to validate the original exact signed JVM value; never replace it with a later clock read.
            String nano=guard.get("source_nano").getAsString();
            require(guard.get("source_nano").getAsJsonPrimitive().isString()
                    && nano.matches("-?(0|[1-9][0-9]{0,18})"));Long.parseLong(nano);
            require(state.getAsJsonObject("movement_budget").equals(action.getAsJsonObject("movement_budget")));
            require(state.getAsJsonObject("menu").equals(screen.getAsJsonObject("menu")));
            boolean open=screen.get("open").getAsBoolean();
            require(open==(before.screen!=null) && open==state.get("screen_open").getAsBoolean()
                    && open==status.getAsJsonObject("screen").get("present").getAsBoolean());
            if(open) for(String field:new String[]{"class","title"})
                require(screen.get(field).equals(status.getAsJsonObject("screen").get(field)));
        } catch(ClientActionRequest.Rejected rejected) { throw rejected; }
        catch(RuntimeException unavailable) { throw new ClientActionRequest.Rejected(409,"capability_snapshot_incoherent"); }
        JsonObject result=new JsonObject();result.addProperty("ok",true);
        result.addProperty("protocol","mineclient-bridge");result.addProperty("schema_version",2);
        result.addProperty("capability_snapshot_schema_version",1);
        JsonObject actionEndpoint=action.deepCopy();
        actionEndpoint.addProperty("protocol","mineclient-bridge");actionEndpoint.addProperty("schema_version",2);
        result.add("status",status);result.add("action",actionEndpoint);result.add("state",state);result.add("screen",screen);
        return ScopedMovementWire.project(result);
    }
    private static void require(boolean condition) {
        if(!condition)throw new ClientActionRequest.Rejected(409,"capability_snapshot_incoherent");
    }
    private CapabilitySnapshot() { }
}
