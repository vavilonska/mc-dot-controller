package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.util.Collection;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** Read-only game-thread proof for the optional official Baritone API variant.
 * No movement command, key clearing, forceCancel, owner grant, or quarantine reset.
 * Every idle verdict queries live objects; only immutable class fingerprints cache.
 */
final class ExternalControllerProof {
    static final String ADAPTER = "baritone-api-neoforge/1.11.3";
    static final String OFFICIAL_JAR_SHA256 = "7f9f40952c49e78388e4e9ceaa6fd91a5b662238e06c997b3de5438177f99d8d";
    record Context(Object minecraft, Object player, Object level, String session,
                   String world, String playerUuid, long tick) {}
    record Facts(String presence, boolean supported, boolean contextMatches, int instances,
                 boolean pathing, boolean currentPath, boolean nextPath, boolean planning,
                 boolean goal, int activeProcesses, int registeredProcesses, int forcedInputs,
                 String reason) {
        boolean idle() { return supported && contextMatches && (presence.equals("absent") && instances == 0
                || presence.equals("present") && instances == 1 && !pathing && !currentPath && !nextPath && !planning && !goal
                && activeProcesses == 0 && registeredProcesses > 0 && forcedInputs == 0); }
    }
    interface Access { Facts inspect(Context context) throws Exception; }
    interface PathRead { boolean read() throws Exception; }
    record PathFacts(boolean planning, boolean pathing, boolean current, boolean next, boolean goal) {}
    static PathFacts readPath(PathRead planning,PathRead pathing,PathRead current,PathRead next,PathRead goal) throws Exception {
        // Baritone's worker publishes current/next BEFORE clearing volatile inProgress.
        // Acquire that volatile publication first. Reading it last can combine old
        // null paths with the newly cleared planner and falsely prove idle.
        boolean calculating=planning.read();
        return new PathFacts(calculating,pathing.read(),current.read(),next.read(),goal.read());
    }

    private static final Access ACCESS = new ReflectiveAccess(ExternalControllerProof.class.getClassLoader());

    static JsonObject snapshot(Context context) { return snapshot(context, ACCESS); }
    static JsonObject snapshot(Context context, Access access) {
        JsonObject j = new JsonObject();
        j.addProperty("schema_version", 1); j.addProperty("controller", "baritone"); j.addProperty("adapter", ADAPTER);
        j.addProperty("source_tick", context.tick()); j.addProperty("source_nano", Long.toString(System.nanoTime()));
        j.addProperty("action_session", context.session()); j.addProperty("world_generation", context.world());
        j.addProperty("player_uuid", context.playerUuid()); j.addProperty("execution_authority", false);
        try {
            if (context.minecraft()==null || context.player()==null || context.level()==null
                    || context.session()==null || context.world()==null || context.playerUuid()==null || context.tick()<0)
                throw new IllegalStateException("context_unavailable");
            Facts f=access.inspect(context); boolean idle=f.idle();
            j.addProperty("status", f.presence().equals("absent") ? "absent" : !f.supported() ? "unknown" : idle ? "idle" : "busy");
            j.addProperty("supported", f.supported()); j.addProperty("idle_proven", idle); j.addProperty("reason", f.reason());
            JsonObject facts = new JsonObject();
            facts.addProperty("instances", f.instances()); facts.addProperty("context_matches", f.contextMatches());
            facts.addProperty("is_pathing", f.pathing()); facts.addProperty("current_path", f.currentPath());
            facts.addProperty("next_path", f.nextPath()); facts.addProperty("planning", f.planning()); facts.addProperty("goal_present", f.goal());
            facts.addProperty("active_process_count", f.activeProcesses()); facts.addProperty("registered_process_count", f.registeredProcesses());
            facts.addProperty("forced_input_count", f.forcedInputs()); j.add("facts", facts);
        } catch (Exception | LinkageError failure) {
            j.addProperty("status", "unknown"); j.addProperty("supported", false); j.addProperty("idle_proven", false);
            j.addProperty("reason", "external_controller_proof_unavailable");
        }
        return j;
    }

    record ManagedProof(JsonObject external,boolean exactOwner,boolean customActive,Object input,String reason) {}
    static ManagedProof managed(Context context,Object expectedProcess,Object expectedGoal) {
        try {
            Facts facts=ACCESS.inspect(context);
            JsonObject external=snapshot(context,ignored -> facts);
            if(!facts.supported()||!facts.contextMatches()||facts.instances()!=1)
                return new ManagedProof(external,false,false,null,"managed_external_proof_unavailable");
            return ((ReflectiveAccess)ACCESS).managed(external,expectedProcess,expectedGoal);
        }catch(Exception|LinkageError unavailable){return new ManagedProof(snapshot(context,ignored -> {
            throw new IllegalStateException("managed_external_proof_unavailable");}),false,false,null,"managed_external_proof_unavailable");}
    }

    /** Public API reflection, with one narrowly pinned read of the complete process registry.
     * API getters omit custom processes and InventoryPauser/Backfill, so reading only those
     * getters or isPathing() cannot establish idle. The API release still obfuscates internals.
     */
    static final class ReflectiveAccess implements Access {
        private final ClassLoader loader;
        private Boolean fingerprints;
        private static final Map<String,String> PINS=Map.of(
            "baritone/api/BaritoneAPI.class", "e0e4d6d2348b9fe892127944b98c2abbf3da854277f4f7577ce60a24a61660c9",
            "baritone/BaritoneProvider.class", "e6b683c02d874d78be766af7b9de983deb9ada553c32592e981799961771c3bc",
            "baritone/a.class", "fa56ca5929d75e02211d303309018e1f279bfb1c601089feaf8314bd52f507b9",
            "baritone/fm.class", "a8835ea175c74724a1f758e35ada261bb6bde816547ad2aa4fccff401e2386cc",
            "baritone/i.class", "4c5eb96811ffbb51533c5a072afb8302525949058be26be2174ddae8870e9a8c",
            "baritone/fj.class", "98e6529f3c0d15278aedd9818c6ec9c811c118bfe33c1618ade6620e1c013a7f",
            "baritone/gd.class", "2b1dabc64f4c4128919b51e8c6347b040940c7a13e0ea1a6f260d3a6129e9c08");
        private static final Map<String,String> PROCESS_PINS=Map.ofEntries(
            Map.entry("baritone.am", "35b28d0892eeedc3e0a7364727a17632b141cc6677859ad7b4f4d0d574911eaa"),
            Map.entry("baritone.dr", "48c20438205753b0eb39031f0abbbdb042507ef4ca65cb1b3fb23b240087e40f"),
            Map.entry("baritone.dt", "8a82b50d9b04cf91723d2d08d480f37e42acab4b00769f2b45e0c6fb30f16b67"),
            Map.entry("baritone.ea", "03543554342d0cfef8a4af98f30c9c2fc95bb1b959b7a7062d35bdc8f7c20077"),
            Map.entry("baritone.eb", "193e46ed4ae42dc8661dc2eafbb36a7ea43c2a7970df73e6856b1bdb917092cb"),
            Map.entry("baritone.ec", "6de6b408b59555d237f0d4141ae0c297c9b81376ab656fed2074c0cfe06ef772"),
            Map.entry("baritone.ee", "0be8ea78f9251dec24a9e582d6beaa5953a370686fca66d3a3b1d3f0e6ae736b"),
            Map.entry("baritone.ei", "6838e637eafb7f025179664828b4114401e4d5a36bc47e4f4ecf1023edfe3426"),
            Map.entry("baritone.ej", "44e9deaff3fa3e8297845b2858f7e5f48506baae92fefe0eae0921aec90e489e"),
            Map.entry("baritone.el", "c20f5f5da727b9d1e7e406ff9469a478c400c98ac5e4e52c2bfb9ee38739ad12"),
            Map.entry("baritone.em", "0a0405a98f8e0c678f0c7f516399b9f3f434ad4227e5afc9ce81cd75e8ef7115"),
            Map.entry("baritone.eu", "0c27977c637ba1397accacc3fae8efd28ccb13f8584a95c06507bc16b0f57882"));
        ReflectiveAccess(ClassLoader loader) { this.loader=loader; }
        boolean fingerprintsSupported() throws Exception {
            if (fingerprints != null) return fingerprints;
            boolean valid=true;
            for (var entry:PINS.entrySet()) {
                try (InputStream stream=loader.getResourceAsStream(entry.getKey())) {
                    if(stream==null){valid=false;break;}
                    byte[] bytes=stream.readNBytes(1_048_577);
                    if(bytes.length>1_048_576 || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(entry.getValue())) {
                        valid=false;break;
                    }
                }
            }
            return fingerprints=valid;
        }
        private Class<?> type(String name) throws ClassNotFoundException { return Class.forName(name, false, loader); }
        private final java.util.Set<String> verifiedProcesses=new java.util.HashSet<>();
        private void exact(Object object,String name) throws Exception {
            if(object==null || object.getClass()!=type(name))throw new IllegalStateException("unpinned_external_implementation");
        }
        private Object field(Object object,String name,String typeName) throws Exception {
            Field match=null;
            for(Field f:object.getClass().getDeclaredFields()) if(f.getName().equals(name)&&f.getType().getName().equals(typeName)) {
                if(match!=null)throw new IllegalStateException("ambiguous_pinned_field");match=f;
            }
            if(match==null || !match.trySetAccessible())throw new IllegalStateException("pinned_field_unavailable");
            return match.get(object);
        }
        /** Reject unknown/custom process classes before calling ANY of their methods. */
        boolean processActive(Object process,boolean managerHasCommand) throws Exception {
            String name=process.getClass().getName();String pin=PROCESS_PINS.get(name);
            if(pin==null || process.getClass()!=type(name))throw new IllegalStateException("custom_process_unsupported");
            if(!verifiedProcesses.contains(name)) {
                try(InputStream stream=loader.getResourceAsStream(name.replace('.','/')+".class")) {
                    if(stream==null)throw new IllegalStateException("process_bytes_missing");
                    byte[] bytes=stream.readNBytes(1_048_577);
                    if(bytes.length>1_048_576 || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(pin))
                        throw new IllegalStateException("process_binary_unsupported");
                }
                verifiedProcesses.add(name);
            }
            // Follow.isActive scans arbitrary entity predicates; a pending predicate is busy.
            if(name.equals("baritone.ei"))return field(process,"a","java.util.function.Predicate")!=null;
            // Backfill.isActive mutates settings and scans world blocks. Never invoke it.
            if(name.equals("baritone.dr")) {
                Object settings=type("baritone.api.BaritoneAPI").getMethod("getSettings").invoke(null);
                Object setting=type("baritone.api.Settings").getField("backfill").get(settings);
                Object enabled=type("baritone.api.Settings$Setting").getField("value").get(setting);
                return !Boolean.FALSE.equals(enabled);
            }
            // InventoryPauser.isActive is ALWAYS true in-world. The pending flag and
            // manager command, not stationary velocity, determine whether it can DEFER.
            if(name.equals("baritone.el"))return inventoryPausePending(bool(field(process,"a","boolean")),managerHasCommand);
            return bool(call(process,"baritone.api.process.IBaritoneProcess","isActive"));
        }
        static boolean inventoryPausePending(boolean requested,boolean managerHasCommand) {
            return requested || managerHasCommand;
        }
        private Object call(Object object, String iface, String method) throws Exception {
            return type(iface).getMethod(method).invoke(object);
        }
        private static boolean bool(Object value) {
            if (!(value instanceof Boolean b)) throw new IllegalArgumentException("boolean_required");
            return b;
        }
        private static boolean present(Object value) {
            if (!(value instanceof Optional<?> optional)) throw new IllegalArgumentException("optional_required");
            return optional.isPresent();
        }
        private Facts unavailable(String reason) {return new Facts("present",false,false,0,false,false,false,false,false,-1,0,-1,reason);}
        private boolean loaderHasBaritone() throws Exception {
            Class<?> mods=type("net.neoforged.fml.ModList"); Object list=mods.getMethod("get").invoke(null);
            Method loaded=mods.getMethod("isLoaded",String.class);
            return bool(loaded.invoke(list,"baritone")) || bool(loaded.invoke(list,"baritoe"));
        }
        ManagedProof managed(JsonObject external,Object expectedProcess,Object expectedGoal) throws Exception {
            Object provider=type("baritone.api.BaritoneAPI").getMethod("getProvider").invoke(null);exact(provider,"baritone.BaritoneProvider");
            Object instance=call(provider,"baritone.api.IBaritoneProvider","getPrimaryBaritone");exact(instance,"baritone.a");
            Object process=call(instance,"baritone.api.IBaritone","getCustomGoalProcess");exact(process,"baritone.ea");
            boolean active=bool(call(process,"baritone.api.process.IBaritoneProcess","isActive"));
            Object goal=call(process,"baritone.api.process.ICustomGoalProcess","getGoal");
            boolean exact=process==expectedProcess && (active?goal==expectedGoal:goal==null);
            Object path=call(instance,"baritone.api.IBaritone","getPathingBehavior");exact(path,"baritone.i");
            Object pathGoal=call(path,"baritone.api.behavior.IPathingBehavior","getGoal");
            exact &= pathGoal==null || pathGoal==expectedGoal;
            Object manager=call(instance,"baritone.api.IBaritone","getPathingControlManager");exact(manager,"baritone.fm");
            Field registry=null;for(Field f:manager.getClass().getDeclaredFields())if(f.getType()==HashSet.class){
                if(registry!=null)throw new IllegalStateException("managed_process_registry_ambiguous");registry=f;}
            if(registry==null||!registry.trySetAccessible())throw new IllegalStateException("managed_process_registry_unavailable");
            Object raw=registry.get(manager);
            if(raw==null||raw.getClass()!=HashSet.class)throw new IllegalStateException("managed_process_registry_changed");
            Collection<?> processes=(Collection<?>)raw;
            if(processes.isEmpty()||processes.size()>64)throw new IllegalStateException("managed_process_registry_bounds");
            for(Object candidate:processes)if(candidate==null||!PROCESS_PINS.containsKey(candidate.getClass().getName()))
                throw new IllegalStateException("managed_custom_process_unsupported");
            boolean found=false;for(Object candidate:processes){
                boolean running=processActive(candidate,false); // InventoryPauser DEFER is not an owner.
                if(candidate==expectedProcess){found=true;exact &= running==active;}else exact &= !running;
            }
            exact &= found;
            Object recent=call(manager,"baritone.api.pathing.calc.IPathingControlManager","mostRecentInControl");
            if(!(recent instanceof Optional<?> controller))throw new IllegalStateException("managed_controller_optional_required");
            exact &= controller.isEmpty()||controller.get()==expectedProcess;
            Object command=call(manager,"baritone.api.pathing.calc.IPathingControlManager","mostRecentCommand");
            if(!(command instanceof Optional<?> current))throw new IllegalStateException("managed_command_optional_required");
            if(current.isPresent()){
                Object value=current.get();exact(value,"baritone.api.process.PathingCommand");
                Object commandGoal=type("baritone.api.process.PathingCommand").getField("goal").get(value);
                Object kind=type("baritone.api.process.PathingCommand").getField("commandType").get(value);
                exact &= (commandGoal==null||commandGoal==expectedGoal)&&kind instanceof Enum<?> enumeration
                    &&!enumeration.name().equals("REQUEST_PAUSE");
            }
            Object input=call(instance,"baritone.api.IBaritone","getInputOverrideHandler");exact(input,"baritone.fj");
            return new ManagedProof(external,exact,active,input,exact?"exact_custom_goal_owner":"managed_external_owner_replaced");
        }
        public Facts inspect(Context context) throws Exception {
            boolean api=loader.getResource("baritone/api/BaritoneAPI.class")!=null;
            boolean present=api || loader.getResource("baritone/api/IBaritoneProvider.class")!=null || loaderHasBaritone();
            if(!present) return new Facts("absent",true,true,0,false,false,false,false,false,0,0,0,"controller_absent");
            if(!api) return unavailable("baritone_api_variant_migration_required");
            if(!fingerprintsSupported()) return unavailable("baritone_version_or_binary_unsupported");
            Object provider=type("baritone.api.BaritoneAPI").getMethod("getProvider").invoke(null);
            exact(provider,"baritone.BaritoneProvider");
            Object all=call(provider,"baritone.api.IBaritoneProvider","getAllBaritones");
            if(!(all instanceof List<?> list) || list.size()!=1) return unavailable("baritone_multiple_or_unknown_instances");
            Object instance=list.get(0);exact(instance,"baritone.a");
            if(instance!=call(provider,"baritone.api.IBaritoneProvider","getPrimaryBaritone")) return unavailable("baritone_primary_instance_mismatch");
            Object player=call(instance,"baritone.api.IBaritone","getPlayerContext");
            exact(player,"baritone.gd");
            boolean same=call(player,"baritone.api.utils.IPlayerContext","minecraft")==context.minecraft()
                    && call(player,"baritone.api.utils.IPlayerContext","player")==context.player()
                    && call(player,"baritone.api.utils.IPlayerContext","world")==context.level();
            if(!same) return unavailable("baritone_player_world_context_mismatch");
            Object path=call(instance,"baritone.api.IBaritone","getPathingBehavior");
            exact(path,"baritone.i");
            String behavior="baritone.api.behavior.IPathingBehavior";
            PathFacts pathFacts=readPath(() -> present(call(path,behavior,"getInProgress")),
                () -> bool(call(path,behavior,"isPathing")), () -> call(path,behavior,"getCurrent")!=null,
                () -> call(path,behavior,"getNext")!=null, () -> call(path,behavior,"getGoal")!=null);
            Object manager=call(instance,"baritone.api.IBaritone","getPathingControlManager");
            exact(manager,"baritone.fm");
            Field registry=null;
            for(Field field:manager.getClass().getDeclaredFields()) if(field.getType()==HashSet.class) {
                if(registry!=null) return unavailable("baritone_process_registry_ambiguous"); registry=field;
            }
            if(registry==null || !registry.trySetAccessible()) return unavailable("baritone_process_registry_unavailable");
            Object raw=registry.get(manager);
            if(raw==null || raw.getClass()!=HashSet.class) return unavailable("baritone_process_registry_unsupported");
            if(!(raw instanceof Collection<?> processes) || processes.isEmpty() || processes.size()>64) return unavailable("baritone_process_registry_bounds");
            // Validate every receiver first: no custom callback can mutate an earlier sample.
            for(Object process:processes) if(process==null || !PROCESS_PINS.containsKey(process.getClass().getName()))
                return unavailable("baritone_custom_process_unsupported");
            boolean managerHasCommand=present(call(manager,"baritone.api.pathing.calc.IPathingControlManager","mostRecentCommand"))
                    || present(call(manager,"baritone.api.pathing.calc.IPathingControlManager","mostRecentInControl"));
            int active=0;
            for(Object process:processes) if(processActive(process,managerHasCommand)) active++;
            Object input=call(instance,"baritone.api.IBaritone","getInputOverrideHandler");
            exact(input,"baritone.fj");
            Class<?> inputType=type("baritone.api.utils.input.Input"); Object[] keys=inputType.getEnumConstants();
            if(keys==null || keys.length<1 || keys.length>32) return unavailable("baritone_input_registry_bounds");
            Method down=type("baritone.api.utils.IInputOverrideHandler").getMethod("isInputForcedDown",inputType);
            int forced=0;for(Object key:keys) if(bool(down.invoke(input,key))) forced++;
            return new Facts("present",true,true,1,pathFacts.pathing(),pathFacts.current(),pathFacts.next(),pathFacts.planning(),pathFacts.goal(),active,processes.size(),forced,
                    "version_pinned_actual_api_sample");
        }
    }
}
