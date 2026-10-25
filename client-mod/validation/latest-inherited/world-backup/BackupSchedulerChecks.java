package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.lang.reflect.*;
import java.util.concurrent.*;
public final class BackupSchedulerChecks {
 static int n;static void check(boolean b,String s){n++;if(!b)throw new AssertionError(s);}
 static Field field(String n)throws Exception{var f=NativeWorldBackup.class.getDeclaredField(n);f.setAccessible(true);return f;}
 static void set(String n,Object v)throws Exception{field(n).set(null,v);}
 static Object get(String n)throws Exception{return field(n).get(null);}
 static JsonObject body(String id){var j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("job_id",id);j.addProperty("expected_action_session","offline-session");j.addProperty("expected_world_generation","offline-world");j.addProperty("expected_player_uuid","19fe5b8a-a2cd-4869-b716-f6abc1c8c7d8");j.addProperty("expected_dimension","minecraft:overworld");return j;}
 public static void main(String[]args)throws Exception{
  long interval=Long.parseLong(args[0]);check(NativeWorldBackup.AUTO_SECONDS==interval,"unchanged JVM interval");boolean enabled=interval>=60&&interval<=86400;
  long due=(long)get("nextAutomatic");var j=NativeWorldBackup.schedulerStatus();check(j.get("automatic_enabled").getAsBoolean()==enabled,"enabled range");
  check(j.get("latest_job_id").isJsonNull()&&j.get("latest_automatic_job_id").isJsonNull(),"no guessed job ID");
  check(j.get("next_due_in_ms").isJsonNull()!=enabled,"disabled has no next due");check(j.get("last_skip_reason").isJsonNull(),"no fabricated skip");
  check(j.get("read_only").getAsBoolean()&&!j.get("progress_filter").getAsBoolean(),"truthful read only/progress flags");
  check((long)get("nextAutomatic")==due&&(int)j.get("job_records").getAsInt()==0,"GET does not schedule or mutate");
  var skip=NativeWorldBackup.class.getDeclaredMethod("skipAutomatic",String.class,long.class);skip.setAccessible(true);skip.invoke(null,"backup_control_or_unknown_busy",System.nanoTime());
  j=NativeWorldBackup.schedulerStatus();check(j.get("last_skip_reason").getAsString().equals("backup_control_or_unknown_busy")&&j.get("last_automatic_decision").getAsString().equals("deferred"),"real skip publication");
  check(j.get("last_check_age_ms").getAsDouble()>=0&&j.get("last_skip_age_ms").getAsDouble()>=0,"monotonic ages");check((long)get("nextAutomatic")==due,"report does not change interval");
  // Actual Job.json and actual failure helper, value-only isolated fixture; never calls Minecraft/start/save.
  var automatic=new NativeWorldBackup.Job(body("39fe5b8a-a2cd-4869-b716-f6abc1c8c7d8"),true,null,null,null);
  var manual=new NativeWorldBackup.Job(body("49fe5b8a-a2cd-4869-b716-f6abc1c8c7d8"),false,null,null,null);
  @SuppressWarnings("unchecked") var jobs=(ConcurrentMap<String,NativeWorldBackup.Job>)get("JOBS");jobs.put(automatic.id,automatic);jobs.put(manual.id,manual);
  set("latestJob",manual);set("latestAutomaticJob",automatic);set("active",automatic);set("snapshot",true);
  j=NativeWorldBackup.schedulerStatus();check(j.get("latest_job_id").getAsString().equals(manual.id)&&j.get("latest_automatic_job_id").getAsString().equals(automatic.id),"latest manual/auto separate");
  check(j.get("active_job_id").getAsString().equals(automatic.id)&&j.get("snapshot_active").getAsBoolean(),"active snapshot visible");
  var fail=NativeWorldBackup.class.getDeclaredMethod("fail",NativeWorldBackup.Job.class,String.class);fail.setAccessible(true);fail.invoke(null,automatic,"backup_server_combat_threat:target_self");
  set("active",null);set("snapshot",false);j=NativeWorldBackup.schedulerStatus();
  check(j.get("latest_failed_job_id").getAsString().equals(automatic.id)&&j.getAsJsonObject("latest_failed_job").get("reason").getAsString().equals("backup_server_combat_threat:target_self"),"failure with exact original ID/reason");
  check(j.getAsJsonObject("latest_automatic_job").get("phase").getAsString().equals("FAILED")&&!j.getAsJsonObject("latest_automatic_job").get("complete").getAsBoolean(),"failed auto not success");
  check(!j.getAsJsonObject("latest_job").get("automatic").getAsBoolean()&&j.getAsJsonObject("latest_automatic_job").get("automatic").getAsBoolean(),"true auto origin");
  check(NativeWorldBackup.status(automatic.id).get("phase").getAsString().equals("FAILED"),"existing per-ID endpoint unchanged");
  j.getAsJsonObject("latest_automatic_job").addProperty("phase","COMPLETE");check(automatic.phase.equals("FAILED"),"GET copies JSON no mutation");
  check(jobs.size()==2&&(long)get("nextAutomatic")==due,"diagnostics retain jobs and due");
  System.out.println("BackupSchedulerChecks interval="+interval+" PASS "+n);
 }
}
