package io.github.campione01.mineclientbridge;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.function.LongSupplier;

/** Standalone finite-input journal. Its monitor serializes invalidation with raw field writes.
 * No game callbacks, futures, network calls, or legacy ownership are implemented here. */
final class RecoveryShortInputLedger {
    static final String PROFILE="recovery_short_input_v1";
    static final String INTERACTION_PROFILE="recovery_interaction_v1";
    static final String INTERACTION_V2_PROFILE="recovery_interaction_v2";
    static final String INTERACTION_V3_PROFILE="recovery_interaction_v3";
    static final String NAVIGATION_V4_PROFILE="recovery_navigation_v4";
    static final String MAINTENANCE_V5_PROFILE="recovery_maintenance_v5";
    static final String SURVIVAL_V6_PROFILE="recovery_survival_v6";
    static boolean survivalProfile(String profile){return SURVIVAL_V6_PROFILE.equals(profile);}
    static boolean twoSecondLeaseProfile(String profile){return maintenanceProfile(profile)||survivalProfile(profile);}
    static boolean maintenanceProfile(String profile){return MAINTENANCE_V5_PROFILE.equals(profile);}
    static boolean geometryProfile(String profile){return navigationProfile(profile)||maintenanceProfile(profile)||survivalProfile(profile);}
    static boolean navigationProfile(String profile){return NAVIGATION_V4_PROFILE.equals(profile);}
    static boolean extendedLeaseProfile(String profile){return INTERACTION_V3_PROFILE.equals(profile)||geometryProfile(profile);}
    static boolean planProfile(String profile){return INTERACTION_V2_PROFILE.equals(profile)||INTERACTION_V3_PROFILE.equals(profile)||geometryProfile(profile);}
    static final int MAX_HISTORY=256,MAINTENANCE_MAX_HISTORY=512,SURVIVAL_MAX_HISTORY=4096;
    /** Runtime admission capacity, not the stored request profile or wire format. */
    enum CapacityMode {
        LEGACY(MAX_HISTORY,1_048_576),MAINTENANCE_V5(MAINTENANCE_MAX_HISTORY,1_048_576),SURVIVAL_V6(SURVIVAL_MAX_HISTORY,4_194_304);
        final int historyLimit,maxFileBytes;
        CapacityMode(int historyLimit,int maxFileBytes){this.historyLimit=historyLimit;this.maxFileBytes=maxFileBytes;}
    }
    record Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId,String profile,int planVersion,String planSha256,String stageId,Placement placement,Survival survival) {
        Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId,String profile,int planVersion,String planSha256,String stageId,Placement placement){this(kind,yaw,pitch,slot,fingerprint,x,y,z,face,blockId,profile,planVersion,planSha256,stageId,placement,null);}
        Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId,String profile,int planVersion,String planSha256,String stageId){this(kind,yaw,pitch,slot,fingerprint,x,y,z,face,blockId,profile,planVersion,planSha256,stageId,null);}
        Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId,String profile,int planVersion,String planSha256){
            this(kind,yaw,pitch,slot,fingerprint,x,y,z,face,blockId,profile,planVersion,planSha256,"");
        }
        Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId){
            this(kind,yaw,pitch,slot,fingerprint,x,y,z,face,blockId,INTERACTION_PROFILE,0,"");
        }
        Operation(String kind,double yaw,double pitch,int slot,String fingerprint,int x,int y,int z,String face,String blockId,String profile){
            this(kind,yaw,pitch,slot,fingerprint,x,y,z,face,blockId,profile,0,"");
        }
        Operation {
            require(Set.of(INTERACTION_PROFILE,INTERACTION_V2_PROFILE,INTERACTION_V3_PROFILE,NAVIGATION_V4_PROFILE,MAINTENANCE_V5_PROFILE,SURVIVAL_V6_PROFILE).contains(profile),"unsupported_operation_profile");
            if(planProfile(profile))require(planVersion==(survivalProfile(profile)?4:maintenanceProfile(profile)?3:navigationProfile(profile)?2:1)&&planSha256!=null&&planSha256.matches("[a-f0-9]{64}"),"invalid_plan_identity");
            else require(planVersion==0&&"".equals(planSha256),"legacy_plan_identity_forbidden");
            require((survivalProfile(profile)?Set.of("move","look","select_hotbar","attack_blaze","consume_bread"):maintenanceProfile(profile)?Set.of("move","look","select_hotbar","break_block","place_block"):navigationProfile(profile)?Set.of("move","look"):Set.of("move","look","select_hotbar","break_block")).contains(kind),"invalid_kind");
            require(geometryProfile(profile)?stageId!=null&&stageId.matches("[A-Za-z0-9._:-]{1,64}"):"".equals(stageId),"invalid_stage_identity");
            require(Double.isFinite(yaw)&&Double.isFinite(pitch),"invalid_angles");
            if(yaw==0)yaw=0;if(pitch==0)pitch=0;
            if(kind.equals("look"))require(yaw>=-180&&yaw<180&&pitch>=-90&&pitch<=90,"invalid_angles");
            if(kind.equals("select_hotbar"))require(survivalProfile(profile)?slot==1||slot==8:slot>=0&&slot<=8,"invalid_slot");
            if(kind.equals("attack_blaze")||kind.equals("consume_bread")){require(survivalProfile(profile)&&survival!=null&&fingerprint!=null&&fingerprint.matches("[a-f0-9]{64}"),"invalid_survival_operation");require(kind.equals("attack_blaze")?survival.maxUseTicks()==0:survival.entityId()==0&&survival.uuid().isEmpty()&&survival.type().isEmpty()&&survival.maxUseTicks()>=1,"invalid_survival_payload");}
            else require(survival==null,"unexpected_survival_payload");
            if(kind.equals("select_hotbar")||kind.equals("break_block"))require(fingerprint!=null&&fingerprint.matches("[a-f0-9]{64}"),"invalid_stack_fingerprint");
            if(kind.equals("place_block"))require(maintenanceProfile(profile)&&placement!=null&&fingerprint!=null&&fingerprint.matches("[a-f0-9]{64}"),"invalid_placement");
            else require(placement==null,"unexpected_placement");
            if(kind.equals("break_block"))require(Set.of("DOWN","UP","NORTH","SOUTH","WEST","EAST").contains(face)&&(maintenanceProfile(profile)?Set.of("minecraft:tnt","minecraft:cut_sandstone","minecraft:chiseled_sandstone").contains(blockId):("minecraft:cobblestone".equals(blockId)||(planProfile(profile)&&"minecraft:nether_wart_block".equals(blockId)))),"unsupported_break_target");
        }
    }
    record Survival(int entityId,String uuid,String type,int maxUseTicks) {
        Survival {require(uuid!=null&&type!=null,"invalid_survival_identity");
            if(maxUseTicks==0)require(UUID.fromString(uuid).toString().equals(uuid)&&"minecraft:blaze".equals(type),"invalid_blaze_identity");
            else require(maxUseTicks>=1&&maxUseTicks<=40&&entityId==0&&uuid.isEmpty()&&type.isEmpty(),"invalid_consume_bound");}
    }
    record Placement(int x,int y,int z,int anchorX,int anchorY,int anchorZ,String anchorBlock,String face,double hitX,double hitY,double hitZ,String itemId) {
        Placement {
            require(Set.of("minecraft:stone","minecraft:sandstone","minecraft:cut_sandstone","minecraft:chiseled_sandstone","minecraft:andesite").contains(anchorBlock),"unsupported_placement_anchor");
            require(Set.of("DOWN","UP","NORTH","SOUTH","WEST","EAST").contains(face)&&"minecraft:andesite".equals(itemId),"unsupported_placement_item_or_face");
            require(Double.isFinite(hitX)&&Double.isFinite(hitY)&&Double.isFinite(hitZ)&&hitX>=anchorX&&hitX<=anchorX+1D&&hitY>=anchorY&&hitY<=anchorY+1D&&hitZ>=anchorZ&&hitZ<=anchorZ+1D,"invalid_hit_point");
            long dx=(long)x-anchorX,dy=(long)y-anchorY,dz=(long)z-anchorZ;
            require(switch(face){case "DOWN"->dx==0&&dy==-1&&dz==0;case "UP"->dx==0&&dy==1&&dz==0;case "NORTH"->dx==0&&dy==0&&dz==-1;case "SOUTH"->dx==0&&dy==0&&dz==1;case "WEST"->dx==-1&&dy==0&&dz==0;case "EAST"->dx==1&&dy==0&&dz==0;default->false;},"placement_not_adjacent");
        }
    }
    record Request(String id,String session,String ownerId,long generation,String world,String player,
                   double forward,double strafe,int samples,boolean jumpFirst,int ttlMs,String observationId,Operation operation) {
        Request(String id,String session,String ownerId,long generation,String world,String player,double forward,double strafe,int samples,boolean jumpFirst,int ttlMs,String observationId){
            this(id,session,ownerId,generation,world,player,forward,strafe,samples,jumpFirst,ttlMs,observationId,null);
        }
        String profile(){return operation==null?PROFILE:operation.profile();}
        String kind(){return operation==null?"move":operation.kind();}
        Request {
            for(String s:List.of(id,session,ownerId,world,player,observationId))
                if(s==null||!s.matches("[A-Za-z0-9._:-]{1,128}"))throw new IllegalArgumentException("invalid_identity");
            if(!UUID.fromString(ownerId).toString().equals(ownerId))throw new IllegalArgumentException("invalid_owner_uuid");
            if(generation<1||generation>9_007_199_254_740_991L||!Double.isFinite(forward)||!Double.isFinite(strafe)||Math.abs(forward)>1||Math.abs(strafe)>1
                ||samples<1||samples>(operation!=null&&operation.kind().equals("break_block")?32:8)||ttlMs<100||ttlMs>(operation!=null&&survivalProfile(operation.profile())&&operation.kind().equals("consume_bread")?4000:2000))throw new IllegalArgumentException("invalid_finite_input");
            if(operation!=null&&maintenanceProfile(operation.profile())&&operation.kind().equals("break_block")&&"minecraft:tnt".equals(operation.blockId()))require(samples==1,"maintenance_tnt_single_call_required");
            if(forward==0)forward=0; if(strafe==0)strafe=0;
            if(operation!=null&&planProfile(operation.profile())&&!geometryProfile(operation.profile()))require(!jumpFirst,"interaction_v2_jump_forbidden");
            if(operation!=null&&!operation.kind().equals("move"))require(forward==0&&strafe==0&&!jumpFirst&&(operation.kind().equals("break_block")||samples==1),"invalid_kind_input");
        }
        String digest(){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(encodeRequest(this)));}
            catch(Exception e){throw new IllegalStateException(e);}}
    }
    static final class Entry {
        final Request request;final long deadline;
        String state="QUEUED",reason="queued";
        int applied;long cancellationGeneration,lastTick=Long.MIN_VALUE;
        boolean invalidated,released=true,effectFenced;
        boolean cleanupQueued,cleanupBlocked,callRunning;
        String gameplay="not_observed";
        RecoveryChallengeLease.Refusal observationRefusal;
        Entry(Request r,long deadline){request=r;this.deadline=deadline;}
        boolean settled(){return state.equals("SETTLED");}
    }
    interface Store { List<Entry> read() throws IOException; void write(Collection<Entry> entries) throws IOException; }
    final String session=UUID.randomUUID().toString();
    private final Store store;private final LongSupplier nano;private final int historyLimit;
    private final Map<String,Entry> history=new LinkedHashMap<>();
    private Entry active;private String owner;private long generation;
    private boolean unknownLock,closed;
    private String lockReason;
    RecoveryShortInputLedger(Store store,LongSupplier nano){this(store,nano,false);}
    RecoveryShortInputLedger(Store store,LongSupplier nano,boolean requireExisting){this(store,nano,requireExisting,false);}
    RecoveryShortInputLedger(Store store,LongSupplier nano,boolean requireExisting,boolean maintenance){
        this(store,nano,requireExisting,maintenance?CapacityMode.MAINTENANCE_V5:CapacityMode.LEGACY);
    }
    RecoveryShortInputLedger(Store store,LongSupplier nano,boolean requireExisting,CapacityMode capacity){
        this.store=store;this.nano=nano;historyLimit=capacity.historyLimit;
        try {
            for(Entry e:store.read()){
                if(history.put(e.request.id(),e)!=null||history.size()>historyLimit)throw new IOException("invalid_ledger_history");
                generation=Math.max(generation,e.request.generation());
                if(owner!=null&&!owner.equals(e.request.ownerId()))throw new IOException("ledger_mixed_owner");
                owner=e.request.ownerId();
                if(!e.settled()){
                    e.state="UNKNOWN";e.reason="restart_unfinished_native_ticket";e.invalidated=true;e.released=false;
                    unknownLock=true;lockReason=e.reason;
                }
            }
            if(unknownLock)store.write(history.values());
            if(requireExisting&&history.isEmpty()){unknownLock=true;lockReason="interaction_existing_journal_required";}
        }catch(Exception e){unknownLock=true;lockReason="native_ledger_unreadable_or_unwritable";}
    }
    synchronized Entry submit(Request r){
        Entry prior=history.get(r.id());
        if(prior!=null){require(prior.request.equals(r),"id_payload_mismatch");return prior;}
        require(!closed,"bridge_closed");require(!unknownLock,"native_unknown_lock");
        require(active==null,"one_in_flight");require(history.size()<historyLimit,"native_history_full");
        require(r.session().equals(session),"session_mismatch");
        require(owner==null||owner.equals(r.ownerId()),"owner_mismatch");
        require(r.generation()==generation+1,"owner_generation_mismatch");
        Entry e=new Entry(r,nano.getAsLong()+r.ttlMs()*1_000_000L);
        owner=r.ownerId();generation=r.generation();history.put(r.id(),e);active=e;
        try{persist(e);}catch(IllegalStateException failure){
            e.reason="admission_not_committed_no_input_possible";
            throw new AdmissionNotCommitted(failure);
        }
        return e;
    }
    static final class AdmissionNotCommitted extends IllegalStateException {
        AdmissionNotCommitted(Throwable cause){super("admission_not_committed_no_input_possible",cause);}
    }
    synchronized Entry lookup(String id,String session,String ownerId,long gen){
        Entry e=history.get(id);require(e!=null,"unknown_action_id");
        require(e.request.session().equals(session)&&e.request.ownerId().equals(ownerId)&&e.request.generation()==gen,"ticket_mismatch");
        expireQueued(e);return e;
    }
    synchronized Entry active(){return active;}
    synchronized Entry latestMaintenanceTarget(){Entry latest=null;for(Entry e:history.values())if(maintenanceProfile(e.request.profile())&&(e.request.kind().equals("break_block")||e.request.kind().equals("place_block")))latest=e;return latest;}
    synchronized int diagnosticEntryCount(){return history.size();}
    synchronized boolean contains(String id){return history.containsKey(id);}
    synchronized boolean closed(){return closed;}
    synchronized boolean residualInput(Entry e){return e!=null&&active==e&&e.effectFenced&&!e.released;}
    synchronized boolean claimCleanup(Entry e){
        if(e==null||active!=e||e.cleanupQueued||e.settled()||(e.state.equals("UNKNOWN")&&e.released))return false;
        e.cleanupQueued=true;return true;
    }
    synchronized void completeCleanup(Entry e){if(e!=null)e.cleanupQueued=false;}
    synchronized boolean locked(){return unknownLock;}
    synchronized String lockReason(){return lockReason;}
    synchronized String owner(){return owner;}
    synchronized long nextGeneration(){return generation+1;}
    synchronized boolean owns(Entry e){return e!=null&&active==e&&!e.invalidated&&!unknownLock&&!closed&&!e.settled();}
    synchronized boolean live(Entry e){
        if(!owns(e))return false;
        if(expired(e)){invalidate(e,"deadline_expired");return false;}
        return true;
    }
    private boolean expired(Entry e){long age=nano.getAsLong()-(e.deadline-e.request.ttlMs()*1_000_000L);return age<0||age>=e.request.ttlMs()*1_000_000L;}
    synchronized void expireQueued(Entry e){if(e!=null&&active==e&&e.state.equals("QUEUED")&&expired(e))invalidate(e,"queue_expired");}
    synchronized void stop(Entry e,String reason){if(e==null||e.settled()||e.state.equals("UNKNOWN"))return;invalidate(e,reason);}
    private void invalidate(Entry e,String reason){
        if(active!=e||(e.request.operation()!=null&&e.invalidated))return;
        e.invalidated=true;e.cancellationGeneration++;e.reason=reason;
        if(!e.effectFenced){e.state="SETTLED";e.released=true;active=null;}
        else {e.state="STOPPING";e.released=false;}
        persist(e);
    }
    /** Caller supplies exclusively raw field writes, after callback-backed context reads. */
    synchronized boolean sample(Entry e,long tick,boolean exactContext,Runnable rawWrites){
        if(!live(e))return false;
        if(!exactContext){invalidate(e,"context_changed");return false;}
        if(e.lastTick==tick)return false;
        if(e.applied>=e.request.samples()){invalidate(e,"sample_bound_reached");return false;}
        e.state="ACTIVE";e.reason="dispatch_fenced";e.effectFenced=true;e.released=false;
        persist(e); // durable BEFORE the first possible raw Input write, on every sample
        if(!live(e))return false;
        try{rawWrites.run();e.applied++;e.lastTick=tick;e.reason="sample_written";return true;}
        catch(RuntimeException|Error failure){unknown(e,"raw_input_write_failed");throw failure;}
    }
    /** Claim is the linearization point: stop before claim prevents entry; after claim the native call may unwind. */
    synchronized boolean claimCall(Entry e,long tick,boolean exactContext){
        if(!live(e))return false;
        if(!exactContext){invalidate(e,"context_changed");return false;}
        if(e.callRunning||e.lastTick==tick)return false;
        if(e.applied>=e.request.samples()){invalidate(e,"call_bound_reached");return false;}
        e.state="ACTIVE";e.reason="native_call_claimed";e.effectFenced=true;e.released=false;
        persist(e);if(!live(e))return false;
        e.callRunning=true;e.lastTick=tick;return true;
    }
    synchronized void completeCall(Entry e){
        require(active==e&&e.callRunning,"native_call_ticket_lost");
        e.callRunning=false;e.applied++;e.reason=e.invalidated?e.reason:"native_call_returned";persist(e);
    }
    synchronized void failedCall(Entry e){e.callRunning=false;unknown(e,"native_call_threw");}
    /** Release is exact captured Input fields only. Never a global key reset or replacement owner. */
    synchronized void release(Entry e,boolean exactOwner,Runnable rawRelease,boolean finish,String reason){
        if(e==null||active!=e||e.callRunning)return;
        if(!exactOwner){unknown(e,"captured_input_owner_changed");return;}
        if(e.state.equals("UNKNOWN")){
            rawRelease.run();e.released=true;
            try{store.write(history.values());}catch(IOException ignored){}
            return; // Physical release never clears uncertainty or the persistent lock.
        }
        try{rawRelease.run();e.released=true;
            if(finish||e.invalidated||e.applied>=e.request.samples()||expired(e)){
                boolean keepReason=e.request.operation()!=null&&e.invalidated;
                e.invalidated=true;e.cancellationGeneration++;e.state="SETTLED";if(!keepReason)e.reason=reason;active=null;
            }
            persist(e);
        }catch(RuntimeException|Error failure){unknown(e,"captured_input_release_failed");throw failure;}
    }
    synchronized void recordObservationRefusal(Entry e,RecoveryChallengeLease.Refusal refusal){
        if(e!=null&&extendedLeaseProfile(e.request.profile())&&owns(e)&&!e.effectFenced)e.observationRefusal=refusal;
    }
    synchronized void rejectQueued(Entry e,String reason){if(active==e&&!e.effectFenced)invalidate(e,reason);}
    synchronized void close(){closed=true;if(active!=null)stop(active,"bridge_stopping");}
    synchronized void unknown(Entry e,String reason){
        unknownLock=true;lockReason=reason;
        if(e!=null){e.state="UNKNOWN";e.reason=reason;e.invalidated=true;e.released=false;e.cancellationGeneration++;}
        try{store.write(history.values());}catch(IOException ignored){/* Existing unfinished journal remains fail-closed on restart. */}
    }
    private void persist(Entry e){try{store.write(history.values());}catch(IOException failure){unknown(e,"native_ledger_write_failed");throw new IllegalStateException("native_ledger_write_failed",failure);}}
    static void require(boolean ok,String reason){if(!ok)throw new IllegalArgumentException(reason);}
    static byte[] encodeRequest(Request r)throws IOException{
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(DataOutputStream d=new DataOutputStream(bytes)){if(r.operation()==null)writeRequest(d,r);else writeInteractionRequest(d,r);}return bytes.toByteArray();
    }
    private static void writeRequest(DataOutputStream d,Request r)throws IOException{
        d.writeUTF(r.id());d.writeUTF(r.session());d.writeUTF(r.ownerId());d.writeLong(r.generation());d.writeUTF(r.world());d.writeUTF(r.player());
        d.writeDouble(r.forward());d.writeDouble(r.strafe());d.writeInt(r.samples());d.writeBoolean(r.jumpFirst());d.writeInt(r.ttlMs());
        d.writeUTF(r.observationId());
    }
    private static Request readRequest(DataInputStream d)throws IOException{return new Request(d.readUTF(),d.readUTF(),d.readUTF(),d.readLong(),d.readUTF(),d.readUTF(),d.readDouble(),d.readDouble(),d.readInt(),d.readBoolean(),d.readInt(),d.readUTF());}
    private static void writeInteractionRequest(DataOutputStream d,Request r)throws IOException{
        d.writeUTF(r.profile());d.writeUTF(r.kind());
        d.writeUTF(r.id());d.writeUTF(r.session());d.writeUTF(r.ownerId());d.writeLong(r.generation());d.writeUTF(r.world());d.writeUTF(r.player());
        d.writeInt(r.ttlMs());d.writeUTF(r.observationId());Operation o=r.operation();
        if(planProfile(r.profile())){d.writeInt(o.planVersion());d.writeUTF(o.planSha256());}
        if(geometryProfile(r.profile()))d.writeUTF(o.stageId());
        switch(r.kind()){
            case "move"->{d.writeDouble(r.forward());d.writeDouble(r.strafe());d.writeInt(r.samples());d.writeBoolean(r.jumpFirst());}
            case "look"->{d.writeDouble(o.yaw());d.writeDouble(o.pitch());}
            case "select_hotbar"->{d.writeInt(o.slot());d.writeUTF(o.fingerprint());}
            case "attack_blaze"->{d.writeInt(o.survival().entityId());d.writeUTF(o.survival().uuid());d.writeUTF(o.survival().type());d.writeUTF(o.fingerprint());}
            case "consume_bread"->{d.writeUTF(o.fingerprint());d.writeInt(o.survival().maxUseTicks());}
            case "place_block"->{Placement p=o.placement();d.writeInt(p.x());d.writeInt(p.y());d.writeInt(p.z());d.writeInt(p.anchorX());d.writeInt(p.anchorY());d.writeInt(p.anchorZ());d.writeUTF(p.anchorBlock());d.writeUTF(p.face());d.writeDouble(p.hitX());d.writeDouble(p.hitY());d.writeDouble(p.hitZ());d.writeUTF(p.itemId());d.writeUTF(o.fingerprint());}
            case "break_block"->{d.writeInt(o.x());d.writeInt(o.y());d.writeInt(o.z());d.writeUTF(o.face());d.writeUTF(o.blockId());d.writeUTF(o.fingerprint());d.writeInt(r.samples());}
            default->throw new IOException("invalid_kind");
        }
    }
    private static Request readInteractionRequest(DataInputStream d)throws IOException{
        String profile=d.readUTF();if(!Set.of(INTERACTION_PROFILE,INTERACTION_V2_PROFILE,INTERACTION_V3_PROFILE,NAVIGATION_V4_PROFILE,MAINTENANCE_V5_PROFILE,SURVIVAL_V6_PROFILE).contains(profile))throw new IOException("ledger_profile");String kind=d.readUTF();
        String id=d.readUTF(),session=d.readUTF(),owner=d.readUTF();long gen=d.readLong();String world=d.readUTF(),player=d.readUTF();int ttl=d.readInt();String obs=d.readUTF();
        int planVersion=0;String planSha="";if(planProfile(profile)){planVersion=d.readInt();planSha=d.readUTF();}
        String stageId=geometryProfile(profile)?d.readUTF():"";
        double forward=0,strafe=0,yaw=0,pitch=0;int samples=1,slot=0,x=0,y=0,z=0;boolean jump=false;String fp="",face="",block="";Placement placement=null;Survival survival=null;
        switch(kind){
            case "move"->{forward=d.readDouble();strafe=d.readDouble();samples=d.readInt();jump=d.readBoolean();}
            case "look"->{yaw=d.readDouble();pitch=d.readDouble();}
            case "select_hotbar"->{slot=d.readInt();fp=d.readUTF();}
            case "attack_blaze"->{survival=new Survival(d.readInt(),d.readUTF(),d.readUTF(),0);fp=d.readUTF();}
            case "consume_bread"->{fp=d.readUTF();survival=new Survival(0,"","",d.readInt());}
            case "place_block"->{placement=new Placement(d.readInt(),d.readInt(),d.readInt(),d.readInt(),d.readInt(),d.readInt(),d.readUTF(),d.readUTF(),d.readDouble(),d.readDouble(),d.readDouble(),d.readUTF());fp=d.readUTF();}
            case "break_block"->{x=d.readInt();y=d.readInt();z=d.readInt();face=d.readUTF();block=d.readUTF();fp=d.readUTF();samples=d.readInt();}
            default->throw new IOException("ledger_kind");
        }
        return new Request(id,session,owner,gen,world,player,forward,strafe,samples,jump,ttl,obs,new Operation(kind,yaw,pitch,slot,fp,x,y,z,face,block,profile,planVersion,planSha,stageId,placement,survival));
    }
    static final class FileStore implements Store,AutoCloseable {
        private final int historyLimit,maxFileBytes;private final Path path;
        private final FileChannel lockChannel;private final FileLock lock;
        FileStore(Path path){this(path,false);}
        FileStore(Path path,boolean maintenance){this(path,maintenance?CapacityMode.MAINTENANCE_V5:CapacityMode.LEGACY);}
        FileStore(Path path,CapacityMode capacity){
            this.historyLimit=capacity.historyLimit;this.maxFileBytes=capacity.maxFileBytes;this.path=path.toAbsolutePath().normalize();
            try{
                noLinks(this.path);Files.createDirectories(this.path.getParent());
                Path lockPath=this.path.resolveSibling(this.path.getFileName()+".lock");noLinks(lockPath);
                lockChannel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
                FileLock acquired;
                try{acquired=lockChannel.tryLock();}catch(RuntimeException failure){lockChannel.close();throw failure;}
                if(acquired==null){lockChannel.close();throw new IOException("native_ledger_already_locked");}lock=acquired;
            }catch(IOException failure){throw new IllegalStateException("native_ledger_lock_failed",failure);}
        }
        private static void noLinks(Path p)throws IOException{for(Path q=p;q!=null;q=q.getParent())if(Files.isSymbolicLink(q))throw new IOException("native_ledger_symlink_forbidden");}
        public void close()throws IOException{lock.release();lockChannel.close();}
        public List<Entry> read()throws IOException{
            noLinks(path);
            if(!Files.exists(path))return List.of();
            if(Files.size(path)>maxFileBytes)throw new IOException("ledger_too_large");
            try(DataInputStream d=new DataInputStream(Files.newInputStream(path))){
                int magic=d.readInt();if(magic!=0x52534931&&magic!=0x52534932)throw new IOException("ledger_magic");
                int count=d.readInt();if(count<0||count>historyLimit)throw new IOException("ledger_count");
                List<Entry> out=new ArrayList<>();for(int i=0;i<count;i++){
                    int tag=magic==0x52534931?0:d.readUnsignedByte();
                    if(tag>1)throw new IOException("ledger_request_tag");
                    Entry e=new Entry(tag==0?readRequest(d):readInteractionRequest(d),0);e.state=d.readUTF();e.reason=d.readUTF();e.applied=d.readInt();e.cancellationGeneration=d.readLong();
                    e.invalidated=d.readBoolean();e.released=d.readBoolean();e.effectFenced=d.readBoolean();if(magic==0x52534932)e.gameplay=d.readUTF();
                    if(extendedLeaseProfile(e.request.profile()))e.observationRefusal=RecoveryChallengeLease.read(d,twoSecondLeaseProfile(e.request.profile()));
                    if(!Set.of("QUEUED","ACTIVE","STOPPING","SETTLED","UNKNOWN").contains(e.state)||e.applied<0||e.applied>e.request.samples()
                        ||(e.settled()&&(!e.invalidated||!e.released)))throw new IOException("ledger_state");out.add(e);
                }
                if(d.read()!=-1)throw new IOException("ledger_trailing_bytes");return out;
            }
        }
        public void write(Collection<Entry> entries)throws IOException{
            if(entries.size()>historyLimit)throw new IOException("ledger_count");
            if(!lock.isValid())throw new IOException("native_ledger_lock_lost");noLinks(path);
            Files.createDirectories(path.toAbsolutePath().getParent());
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(DataOutputStream d=new DataOutputStream(bytes)){
                d.writeInt(0x52534932);d.writeInt(entries.size());for(Entry e:entries){d.writeByte(e.request.operation()==null?0:1);if(e.request.operation()==null)writeRequest(d,e.request);else writeInteractionRequest(d,e.request);d.writeUTF(e.state);d.writeUTF(e.reason);d.writeInt(e.applied);
                    d.writeLong(e.cancellationGeneration);d.writeBoolean(e.invalidated);d.writeBoolean(e.released);d.writeBoolean(e.effectFenced);d.writeUTF(e.gameplay);if(extendedLeaseProfile(e.request.profile()))RecoveryChallengeLease.write(d,e.observationRefusal);}
            }
            // Never commit bytes the same mode cannot reopen, including on cleanup/restart.
            if(bytes.size()>maxFileBytes)throw new IOException("ledger_too_large");
            Path tmp=path.resolveSibling(path.getFileName()+".tmp");
            noLinks(tmp);
            try(FileChannel c=FileChannel.open(tmp,StandardOpenOption.CREATE,StandardOpenOption.TRUNCATE_EXISTING,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)){
                ByteBuffer b=ByteBuffer.wrap(bytes.toByteArray());while(b.hasRemaining())c.write(b);c.force(true);
            }
            Files.move(tmp,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            try(FileChannel directory=FileChannel.open(path.toAbsolutePath().getParent(),StandardOpenOption.READ)){directory.force(true);}
        }
    }
}
