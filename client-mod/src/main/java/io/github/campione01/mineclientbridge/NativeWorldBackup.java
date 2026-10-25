package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import net.minecraft.client.Minecraft;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.level.storage.LevelResource;
import net.neoforged.fml.ModList;

/** Explicit private-singleplayer save barrier. Never controls inputs, restores worlds, or deletes backups. */
final class NativeWorldBackup {
    static final Set<String> FIELDS=Set.of("schema_version","job_id","expected_action_session","expected_world_generation","expected_player_uuid","expected_dimension");
    private static final Set<String> AUDITED_MODS=Set.of("minecraft","neoforge","mineclient_bridge");
    private static final ConcurrentMap<String,Job> JOBS=new ConcurrentHashMap<>();
    private static final ExecutorService ARCHIVER=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"MDC-backup-archive");t.setDaemon(true);return t;});
    private static volatile Job active;
    private static volatile boolean snapshot;
    private static BackupSaveValidation.Errors saveFaultMonitor;
    private static String monitorFailure="not_installed";
    static synchronized void install(){
        if(saveFaultMonitor!=null)return;
        try{saveFaultMonitor=new BackupSaveValidation.Errors(true);monitorFailure=null;}
        catch(Exception failure){monitorFailure="backup_save_error_channel_unavailable:"+shortReason(failure);}
    }
    // Startup setting only. Explicit single-shot is the initial deployed mode; 0 is the default.
    static final long AUTO_SECONDS=Long.getLong("mineclient.backup.intervalSeconds",0L);
    private static volatile long nextAutomatic=System.nanoTime()+TimeUnit.SECONDS.toNanos(Math.max(60,AUTO_SECONDS));
    private static volatile Job latestJob,latestAutomaticJob,latestFailedJob;
    private static volatile long lastAutomaticCheckNano,lastSkipNano;
    private static volatile String lastAutomaticDecision="not_checked",lastSkipReason;
    static final class Job {
        final String id,session,world,uuid,dimension;final JsonObject request;final boolean automatic;
        final MinecraftServer server;final Object clientPlayer,clientLevel;
        final long accepted=System.nanoTime();
        volatile String phase="QUEUED",reason="accepted";volatile long criticalNanos;
        volatile Path stage,archive;volatile JsonObject validation;volatile int fileCount;
        Job(JsonObject body,Minecraft mc,boolean automatic){this(body,automatic,mc.getSingleplayerServer(),mc.player,mc.level);}
        // Value-only construction also lets offline diagnostics exercise the actual Job.json schema.
        Job(JsonObject body,boolean automatic,MinecraftServer server,Object clientPlayer,Object clientLevel){
            this.automatic=automatic;request=body.deepCopy();id=s(body,"job_id");session=s(body,"expected_action_session");world=s(body,"expected_world_generation");
            uuid=s(body,"expected_player_uuid");dimension=s(body,"expected_dimension");this.server=server;this.clientPlayer=clientPlayer;this.clientLevel=clientLevel;}
        JsonObject json(){JsonObject j=new JsonObject();j.addProperty("ok",true);j.addProperty("backup_schema_version",1);j.addProperty("job_id",id);
            j.addProperty("phase",phase);j.addProperty("reason",reason);j.addProperty("complete",phase.equals("COMPLETE"));
            j.addProperty("simulation_barrier_ms",criticalNanos/1_000_000.0);j.addProperty("file_count",fileCount);
            j.addProperty("stage_path",stage==null?null:stage.toString());j.addProperty("archive_path",archive==null?null:archive.toString());
            j.addProperty("automatic",automatic);j.addProperty("automatic_interval_seconds",AUTO_SECONDS);j.addProperty("no_live_restore",true);
            if(validation!=null)j.add("validation",validation.deepCopy());return j;}
    }
    static synchronized JsonObject start(JsonObject body){return start(body,false);}
    private static synchronized JsonObject start(JsonObject body,boolean automatic){
        Minecraft mc=Minecraft.getInstance();check(mc.isSameThread(),"backup_client_thread_required");
        validateRequest(body);
        Job old=JOBS.get(s(body,"job_id"));if(old!=null){check(old.request.equals(body),"backup_job_id_payload_mismatch");return old.json();}
        check(active==null,"backup_job_busy");check(JOBS.size()<64,"backup_job_history_full");
        check(saveFaultMonitor!=null,monitorFailure);
        try{saveFaultMonitor.assertClean();}catch(IOException failure){throw new ClientActionRequest.Rejected(409,"backup_prior_save_error_requires_inspection");}
        String problem=clientProblem(mc);check(problem==null,problem);
        check(s(body,"expected_action_session").equals(ClientActions.session()),"backup_session_changed");
        check(s(body,"expected_world_generation").equals(WorldGeneration.current(mc.level)),"backup_world_changed");
        check(s(body,"expected_player_uuid").equals(mc.player.getStringUUID()),"backup_player_changed");
        check(s(body,"expected_dimension").equals(mc.level.dimension().location().toString()),"backup_dimension_changed");
        Set<String> mods=new TreeSet<>();ModList.get().getMods().forEach(m->mods.add(m.getModId()));
        check(mods.equals(AUDITED_MODS),"backup_unaudited_mod_set");
        check(net.minecraft.SharedConstants.getCurrentVersion().getId().equals("1.21.1")
            && ModList.get().getModContainerById("neoforge").orElseThrow().getModInfo().getVersion().toString().equals("21.1.255"),"backup_unaudited_runtime_version");
        Job job=new Job(body,mc,automatic);JOBS.put(job.id,job);latestJob=job;if(automatic)latestAutomaticJob=job;active=job;snapshot=true;
        try {job.server.execute(()->saveAndStage(job));}
        catch(RuntimeException failed){fail(job,"server_schedule_failed");active=null;snapshot=false;}
        return job.json();
    }
    static void validateRequest(JsonObject body){
        check(body.keySet().equals(FIELDS),"backup_closed_fields");
        check(body.get("schema_version").isJsonPrimitive()&&body.getAsJsonPrimitive("schema_version").isNumber()
            &&body.get("schema_version").getAsString().equals("1"),"backup_schema");
        try{check(UUID.fromString(s(body,"job_id")).toString().equals(s(body,"job_id")),"backup_uuid_required");
            UUID.fromString(s(body,"expected_player_uuid"));}
        catch(IllegalArgumentException bad){throw new ClientActionRequest.Rejected(400,"backup_uuid_required");}
        for(String key:FIELDS)if(!key.equals("schema_version"))s(body,key);
    }
    static JsonObject status(String id){Job j=JOBS.get(id);if(j==null)throw new ClientActionRequest.Rejected(404,"backup_job_not_found");return j.json();}
    /** GET-only cached scheduler facts; no client-thread wait, no current-world reads/actions. */
    static JsonObject schedulerStatus(){
        long now=System.nanoTime();Job current=active,last=latestJob,automatic=latestAutomaticJob,failed=latestFailedJob;
        boolean enabled=AUTO_SECONDS>=60&&AUTO_SECONDS<=86400;
        JsonObject j=new JsonObject();j.addProperty("ok",true);j.addProperty("backup_scheduler_schema_version",1);
        j.addProperty("read_only",true);j.addProperty("clock","monotonic_wall_time_checked_on_client_tick");
        j.addProperty("sample_nano",Long.toString(now));j.addProperty("automatic_enabled",enabled);
        j.addProperty("automatic_interval_seconds",AUTO_SECONDS);j.addProperty("progress_filter",false);
        j.addProperty("next_due_in_ms",enabled?Math.max(0,nextAutomatic-now)/1_000_000.0:null);
        j.addProperty("last_check_age_ms",lastAutomaticCheckNano==0?null:(now-lastAutomaticCheckNano)/1_000_000.0);
        j.addProperty("last_automatic_decision",lastAutomaticDecision);
        j.addProperty("last_skip_reason",lastSkipReason);j.addProperty("last_skip_age_ms",lastSkipNano==0?null:(now-lastSkipNano)/1_000_000.0);
        j.addProperty("snapshot_active",snapshot);j.addProperty("job_records",JOBS.size());j.addProperty("max_job_records",64);
        j.addProperty("active_job_id",current==null?null:current.id);
        j.addProperty("latest_job_id",last==null?null:last.id);if(last!=null)j.add("latest_job",last.json());
        j.addProperty("latest_automatic_job_id",automatic==null?null:automatic.id);if(automatic!=null)j.add("latest_automatic_job",automatic.json());
        j.addProperty("latest_failed_job_id",failed==null?null:failed.id);if(failed!=null)j.add("latest_failed_job",failed.json());
        return j;
    }
    private static void skipAutomatic(String why,long now){lastAutomaticCheckNano=now;lastSkipNano=now;lastSkipReason=why;lastAutomaticDecision="deferred";}
    private static void fail(Job job,String why){job.reason=why;job.phase="FAILED";latestFailedJob=job;}
    static boolean blocksMutation(String path){return snapshot&&!path.startsWith("/control/backup/")
        &&!Set.of("/control/action/cancel","/control/release-all","/control/fall-rescue/disarm").contains(path);}
    static void requireNoSnapshot(){check(!snapshot,"world_backup_snapshot_in_progress");}
    static void clientTick(Minecraft mc){
        if(AUTO_SECONDS<60||AUTO_SECONDS>86400)return;
        long now=System.nanoTime();if(now<nextAutomatic)return;
        if(active!=null){skipAutomatic("backup_job_busy",now);return;}
        lastAutomaticCheckNano=now;nextAutomatic=now+TimeUnit.SECONDS.toNanos(10);
        String problem=clientProblem(mc);if(problem!=null){skipAutomatic(problem,now);return;}
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("job_id",UUID.randomUUID().toString());
        j.addProperty("expected_action_session",ClientActions.session());j.addProperty("expected_world_generation",WorldGeneration.current(mc.level));
        j.addProperty("expected_player_uuid",mc.player.getStringUUID());j.addProperty("expected_dimension",mc.level.dimension().location().toString());
        try{start(j,true);nextAutomatic=System.nanoTime()+TimeUnit.SECONDS.toNanos(AUTO_SECONDS);lastAutomaticDecision="accepted";}
        catch(RuntimeException refused){skipAutomatic("admission_refused:"+shortReason(refused),System.nanoTime());}
    }
    private static String clientProblem(Minecraft mc){
        if(mc.player==null||mc.level==null||mc.getSingleplayerServer()==null||mc.getSingleplayerServer().isPublished())return "backup_private_singleplayer_required";
        if(NativeRecoveryShortInput.ENABLED)return "backup_recovery_mode_unsupported";
        if(!mc.player.isAlive()||!mc.player.onGround()||mc.player.isOnFire()||mc.player.isInWaterOrBubble()||mc.player.isInLava()||mc.player.isPassenger())return "backup_player_not_safe_idle";
        if(mc.player.getDeltaMovement().horizontalDistanceSqr()>.0004||mc.player.hurtTime>0)return "backup_player_moving_or_hurt";
        if(mc.isPaused()||mc.screen!=null)return "backup_gameplay_screen_required";
        if(!ClientActions.backupSafe()||ClientActions.ownsInput()||!ExternalControllerGuard.idle(mc))return "backup_control_or_unknown_busy";
        if(!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean()||GuardedGameMovement.LEASES.status().ownerRequestId()!=null)return "backup_input_not_neutral";
        if(NativePortalHandoff.status().get("armed").getAsBoolean()||NativeFallRescue.status().get("armed").getAsBoolean())return "backup_assist_armed";
        // Mere client-side presence behind walls is not a snapshot hazard. The server task
        // evaluates fresh LOS, actual target, contact and projectiles immediately before save.
        return null;
    }
    /** Server-authoritative instantaneous risk, not a promise that an arbitrary room is safe. */
    private static void requireNoServerThreat(ServerPlayer player) throws IOException {
        for(var entity:player.serverLevel().getEntitiesOfClass(net.minecraft.world.entity.Entity.class,
                player.getBoundingBox().inflate(64),e->e.isAlive()&&(e instanceof Mob||e instanceof Projectile))) {
            double distanceSquared=entity.distanceToSqr(player);
            boolean targetSelf=entity instanceof Mob mob&&mob.getTarget()==player;
            boolean enemy=entity instanceof Enemy, projectile=entity instanceof Projectile;
            if(!targetSelf&&!enemy&&!projectile)continue;
            boolean contact=entity.getBoundingBox().intersects(player.getBoundingBox().inflate(.2));
            boolean visible=entity instanceof Mob mob?mob.hasLineOfSight(player):player.hasLineOfSight(entity);
            String risk=threatReason(targetSelf,enemy,projectile,visible,contact,distanceSquared);
            BackupSaveValidation.require(risk==null,"backup_server_combat_threat:"+risk);
        }
    }
    // Pure policy seam: inputs above are taken directly from this same server-thread world.
    static String threatReason(boolean targetSelf,boolean enemy,boolean projectile,boolean visible,
            boolean contact,double distanceSquared) {
        if(!Double.isFinite(distanceSquared)||distanceSquared<0)return "invalid_threat_position";
        if(targetSelf)return "target_self"; // Includes an angry Enderman temporarily behind cover.
        if((enemy||projectile)&&contact)return "close_contact";
        if(enemy&&visible&&distanceSquared<=32*32)return "visible_hostile";
        if(projectile&&visible&&distanceSquared<=16*16)return "visible_projectile";
        return null; // Occluded, not targeting us, and no contact: no blanket 32m clear-area demand.
    }
    private static void saveAndStage(Job job){
        long begin=System.nanoTime();BackupStageFiles.Stage stage=null;Path archiveTarget=null;boolean staged=false;
        try {
            if(begin-job.accepted>TimeUnit.SECONDS.toNanos(5))throw new IOException("backup_queued_too_long");
            Minecraft mc=Minecraft.getInstance();MinecraftServer server=job.server;
            BackupSaveValidation.require(server.isSameThread()&&server.isSingleplayer()&&!server.isPublished()&&server==mc.getSingleplayerServer()&&mc.player==job.clientPlayer&&mc.level==job.clientLevel,"backup_context_changed_before_save");
            ServerPlayer p=server.getPlayerList().getPlayer(UUID.fromString(job.uuid));
            BackupSaveValidation.require(p!=null&&server.getPlayerList().getPlayerCount()==1&&p.isAlive()&&p.onGround()
                &&!p.isOnFire()&&!p.isInWaterOrBubble()&&!p.isInLava()&&!p.isPassenger()&&p.hurtTime==0,"backup_server_player_not_safe_idle");
            BackupSaveValidation.require(p.serverLevel().dimension().location().toString().equals(job.dimension),"backup_server_dimension_changed");
            BackupSaveValidation.require(p.getDeltaMovement().horizontalDistanceSqr()<.0004,"backup_server_player_moving");
            requireNoServerThreat(p);
            for(var level:server.getAllLevels())BackupSaveValidation.require(!level.noSave,"backup_save_off_refused_flags_unchanged");
            Path world=server.getWorldPath(LevelResource.ROOT).toAbsolutePath().normalize();
            BackupSaveValidation.require(world.equals(world.toRealPath()),"backup_source_symlink_refused");
            Path root=mc.gameDirectory.toPath().toAbsolutePath().normalize().resolve("mdc-backups");
            BackupSaveValidation.require(!root.startsWith(world),"backup_destination_inside_world");
            Files.createDirectories(root);BackupSaveValidation.require(!Files.isSymbolicLink(root)&&root.toRealPath().equals(root),"backup_destination_symlink");
            Path dir=root.resolve(job.id+".stage");job.stage=dir;
            long deadline=begin+TimeUnit.SECONDS.toNanos(30);
            BackupStageFiles.Checkpoint boundary=(phase,path)->{if(System.nanoTime()>deadline)throw new IOException("backup_deadline_at_safe_boundary:"+phase);};
            try(BackupSaveValidation.Errors errors=new BackupSaveValidation.Errors()) {
                BackupSaveValidation.requireSettledChunks(server);
                var capture=BackupSaveValidation.capture(server,p);
                job.phase="SAVING";job.reason="saving_and_draining_known_writers";
                saveFaultMonitor.assertClean();server.saveEverything(true,true,true);
                BackupSaveValidation.drainPoiAndSavedData(server);BackupSaveValidation.requireSettledChunks(server);errors.assertClean();saveFaultMonitor.assertClean();boundary.check("drained",world);
                job.phase="STAGING";job.reason="server_thread_immutable_copy";
                stage=BackupStageFiles.copy(world,dir,boundary);job.fileCount=(int)stage.members().stream().filter(m->!m.path().endsWith("/")).count();
                job.validation=BackupSaveValidation.validate(stage.world(),server,p,capture);
                errors.assertClean();boundary.check("validated",dir);
                JsonObject manifest=new JsonObject();manifest.addProperty("backup_schema_version",1);manifest.addProperty("job_id",job.id);
                manifest.addProperty("captured_utc",Instant.now().toString());manifest.addProperty("consistency","server-task-save-drain-staged-fixed-modset");
                manifest.addProperty("minecraft_version","1.21.1");manifest.addProperty("neoforge_version","21.1.255");
                manifest.addProperty("world_directory",world.getFileName().toString());manifest.addProperty("player_uuid",job.uuid);
                manifest.addProperty("action_session_at_capture",job.session);manifest.addProperty("old_actions_must_not_be_replayed",true);
                manifest.addProperty("source_save_flags_unchanged",true);manifest.addProperty("no_arbitrary_mod_async_guarantee",true);
                manifest.add("validation",job.validation.deepCopy());JsonArray mods=new JsonArray();AUDITED_MODS.stream().sorted().forEach(mods::add);manifest.add("audited_mod_ids",mods);
                Files.writeString(dir.resolve("SNAPSHOT.json"),new GsonBuilder().setPrettyPrinting().create().toJson(manifest),StandardOpenOption.CREATE_NEW);
                try(var file=java.nio.channels.FileChannel.open(dir.resolve("SNAPSHOT.json"),StandardOpenOption.WRITE)){file.force(true);}
                BackupStageFiles.commit(stage,boundary);errors.assertClean();saveFaultMonitor.assertClean();boundary.check("stage_committed",dir);
            }
            job.phase="ARCHIVING";job.reason="simulation_released_background_zip";
            archiveTarget=root.resolve(job.id+".archive");staged=true;
        } catch(Exception failure){fail(job,shortReason(failure));}
        finally {job.criticalNanos=System.nanoTime()-begin;snapshot=false;}
        if(staged){final BackupStageFiles.Stage frozen=stage;final Path target=archiveTarget;
            try{ARCHIVER.execute(()->archive(job,frozen,target));}
            catch(RuntimeException failure){fail(job,"archive_schedule_failed");clearActive(job);}
        }else clearActive(job);
    }
    private static synchronized void clearActive(Job job){if(active==job)active=null;}
    private static void archive(Job job,BackupStageFiles.Stage stage,Path target){
        try{job.archive=BackupStageFiles.zip(stage,target,(phase,path)->{});job.phase="COMPLETE";job.reason="validated_stage_archive_committed";}
        catch(Exception failure){fail(job,"archive_failed:"+shortReason(failure));}
        finally {clearActive(job);}
    }
    private static String shortReason(Exception e){String text=e.getClass().getSimpleName()+":"+String.valueOf(e.getMessage());return text.length()>512?text.substring(0,512):text;}
    private static String s(JsonObject j,String k){check(j.has(k)&&j.get(k).isJsonPrimitive()&&j.getAsJsonPrimitive(k).isString(),"backup_string_"+k);return j.get(k).getAsString();}
    private static void check(boolean ok,String why){if(!ok)throw new ClientActionRequest.Rejected(409,why);}
}
