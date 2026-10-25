package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import net.minecraft.nbt.*;
import net.minecraft.stats.ServerStatsCounter;
import org.apache.logging.log4j.Level;
import org.apache.logging.log4j.core.config.Configurator;
public final class BackupNativeChecks {
    static int n;static void check(boolean v,String m){n++;if(!v)throw new AssertionError(m);}
    interface F{void run() throws Exception;}
    static void reject(F f,String m)throws Exception{n++;try{f.run();throw new AssertionError("accepted "+m);}catch(java.io.IOException|ClientActionRequest.Rejected expected){}}
    static final String UUID0="19fe5b8a-a2cd-4869-b716-f6abc1c8c7d8";
    static JsonObject body(){return JsonParser.parseString("{\"schema_version\":1,\"job_id\":\"39fe5b8a-a2cd-4869-b716-f6abc1c8c7d8\",\"expected_action_session\":\"session\",\"expected_world_generation\":\"world\",\"expected_player_uuid\":\""+UUID0+"\",\"expected_dimension\":\"minecraft:overworld\"}").getAsJsonObject();}
    static void write(Path w,BackupSaveValidation.Capture c,CompoundTag level)throws Exception{
        Files.createDirectories(w.resolve("playerdata"));Files.createDirectories(w.resolve("stats"));Files.createDirectories(w.resolve("advancements"));
        NbtIo.writeCompressed(c.player(),w.resolve("playerdata/"+c.uuid()+".dat"));
        Files.writeString(w.resolve("stats/"+c.uuid()+".json"),c.stats().toString());Files.writeString(w.resolve("advancements/"+c.uuid()+".json"),c.advancements().toString());
        CompoundTag root=new CompoundTag();root.put("Data",level.copy());NbtIo.writeCompressed(root,w.resolve("level.dat"));
    }
    public static void main(String[] args)throws Exception{
        Configurator.setRootLevel(Level.INFO);
        NativeWorldBackup.validateRequest(body());check(NativeWorldBackup.AUTO_SECONDS==0,"automatic disabled default");
        for(String k:body().keySet()){JsonObject b=body();b.remove(k);reject(()->NativeWorldBackup.validateRequest(b),"missing "+k);}
        JsonObject wrong=body();wrong.addProperty("directory","/outside");reject(()->NativeWorldBackup.validateRequest(wrong),"arbitrary filesystem path forbidden");
        JsonObject stringSchema=body();stringSchema.addProperty("schema_version","1");reject(()->NativeWorldBackup.validateRequest(stringSchema),"strict schema type");
        JsonObject uuid=body();uuid.addProperty("job_id","same-id");reject(()->NativeWorldBackup.validateRequest(uuid),"uuid");
        ActionRegistry registry=new ActionRegistry();check(registry.backupSafe(),"new ordinary registry idle");
        var request=ClientActionRequest.parse(JsonParser.parseString("{\"action_id\":\"test-backup\",\"action\":\"follow_path\",\"timeout_ms\":5000,\"waypoints\":[{\"x\":0,\"y\":64,\"z\":0}]}").getAsJsonObject());
        var entry=registry.begin(request);check(!registry.backupSafe(),"active refuses");registry.finishAfterCleanup("succeeded","path_reached",true);check(registry.backupSafe(),"known released permits");
        entry.result.addProperty("unknown_outcome",true);check(!registry.backupSafe(),"unknown refuses");entry.result.addProperty("unknown_outcome",false);entry.result.addProperty("requires_handoff",true);check(!registry.backupSafe(),"handoff refuses");entry.result.remove("requires_handoff");entry.result.addProperty("input_release_confirmed",false);check(!registry.backupSafe(),"release unconfirmed refuses");
        entry.result.addProperty("input_release_confirmed",true);JsonObject nested=new JsonObject();nested.addProperty("unknown_attack_outcome",true);entry.result.add("nested",nested);check(!registry.backupSafe(),"nested uncertain refuses");entry.result.remove("nested");
        CompoundTag player=new CompoundTag();player.putString("UUID",UUID0);player.putFloat("Health",17);player.putString("Dimension","minecraft:overworld");player.put("Inventory",new ListTag());
        JsonElement stats=JsonParser.parseString("{\"stats\":{\"test\":3},\"DataVersion\":3955}"),adv=JsonParser.parseString("{\"DataVersion\":3955}");
        var capture=new BackupSaveValidation.Capture(UUID0,player,stats,adv,125,50);
        CompoundTag level=new CompoundTag();level.putLong("Time",125);level.putString("LevelName","MDC-BACKUP-TEST");level.put("Player",player.copy());level.putLong("LastPlayed",100);
        Path w=Files.createTempDirectory("mdc-backup-native-checks-");write(w,capture,level);
        var result=BackupSaveValidation.validateSavedFiles(w,capture,capture,level);check(result.get("player_nbt_exact").getAsBoolean(),"real compressed NBT validation");
        CompoundTag otherTime=level.copy();otherTime.putLong("LastPlayed",99999);check(BackupSaveValidation.validateSavedFiles(w,capture,capture,otherTime)!=null,"wall clock LastPlayed excluded only");
        var advanced=new BackupSaveValidation.Capture(UUID0,player,stats,adv,126,51);reject(()->BackupSaveValidation.validateSavedFiles(w,capture,advanced,level),"tick advanced");
        CompoundTag changed=player.copy();changed.putFloat("Health",12);var changedCapture=new BackupSaveValidation.Capture(UUID0,changed,stats,adv,125,50);
        reject(()->BackupSaveValidation.validateSavedFiles(w,capture,changedCapture,level),"player mutation during save");
        NbtIo.writeCompressed(changed,w.resolve("playerdata/"+UUID0+".dat"));reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"old or different player persisted");write(w,capture,level);
        Files.writeString(w.resolve("stats/"+UUID0+".json"),"{}");reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"valid but stale stats");write(w,capture,level);
        Files.writeString(w.resolve("advancements/"+UUID0+".json"),"{}");reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"valid but stale advancements");write(w,capture,level);
        CompoundTag stale=level.copy();stale.putLong("Time",124);write(w,capture,stale);reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"valid stale level");write(w,capture,level);
        Files.createDirectory(w.resolve("data"));Files.writeString(w.resolve("data/broken.json"),"[1]");reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"other invalid data JSON");Files.delete(w.resolve("data/broken.json"));
        Files.writeString(w.resolve("data/broken.dat"),"not nbt");reject(()->BackupSaveValidation.validateSavedFiles(w,capture,capture,level),"truncated compressed NBT");
        try(var errors=new BackupSaveValidation.Errors()){errors.assertClean();check(true,"error channel installed clean");org.apache.logging.log4j.LogManager.getLogger("net.minecraft.world.level.storage.PlayerDataStorage").warn("Failed to save player data for TEST-fixture");reject(errors::assertClean,"swallowed player WARN captured");}
        try(var errors=new BackupSaveValidation.Errors(true)){org.apache.logging.log4j.LogManager.getLogger("net.minecraft.server.MinecraftServer").warn("Can't keep up! Running behind");errors.assertClean();check(true,"lag does not poison persistent save monitor");}
        for(String message:List.of("Failed to store chunk TEST", "Failed to synchronize chunks", "Failed to store entity chunk TEST")) {
            try(var errors=new BackupSaveValidation.Errors(true)){org.apache.logging.log4j.LogManager.getLogger("net.minecraft.world.level.chunk.storage.IOWorker").error(message);reject(errors::assertClean,"historical original IO failure: "+message);}
        }
        // Exercise the REAL 1.21.1 save method's swallowed filesystem failure, no Minecraft process/world.
        Path directoryInsteadOfFile=Files.createDirectory(w.resolve("stats-is-directory"));
        ServerStatsCounter counter=new ServerStatsCounter(null,directoryInsteadOfFile.toFile()){@Override protected String toJson(){return "{\"stats\":{}}";}};
        try(var errors=new BackupSaveValidation.Errors()){counter.save();check(true,"actual stats save swallowed IO and returned");reject(errors::assertClean,"actual swallowed stats save failure captured");}
        check(Files.isDirectory(directoryInsteadOfFile),"fault fixture did not alter target permissions");
        System.out.println("BackupNativeChecks PASS "+n);
    }
}
