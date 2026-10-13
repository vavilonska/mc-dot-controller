package io.github.campione01.mineclientbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.function.LongSupplier;

/** Single-owner native-paced read job. No Minecraft dependency, input, sleep or hidden replay. */
final class TerrainAcquisition {
    static final long DEADLINE = 3_000_000_000L, RETENTION = 30_000_000_000L;
    static final int RESPONSE_LIMIT = 256 * 1024, MANIFEST_LIMIT = 32 * 1024,
            RETAINED_LIMIT = 2 * 1024 * 1024, MAX_IDENTITIES = 32;
    private static final Gson METADATA = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();

    /** Identity references are captured/compared only on the actual client thread. */
    record Context(Object level, Object player, Object gameMode, Object screen, Object menu,
                   Object configuration, JsonObject wire, long tick,ObservationClientClock.Stamp clock) {
        Context(Object level,Object player,Object gameMode,Object screen,Object menu,Object configuration,JsonObject wire,long tick) {
            this(level,player,gameMode,screen,menu,configuration,wire,tick,null);
        }
        long chronology() {return clock==null?tick:clock.count();}
        boolean same(Context other) {
            return other!=null && level==other.level && player==other.player && gameMode==other.gameMode
                    && screen==other.screen && menu==other.menu && configuration==other.configuration
                    && wire.equals(other.wire) && (clock==null ? other.clock==null && other.tick>=tick:
                        clock.sameDomain(other.clock) && other.clock.count()>=clock.count());
        }
    }
    record Capture(JsonObject body, Context context) { }
    record Page(JsonObject body, long actualStart, long end) { }
    interface Source {
        Capture capture();
        Context context();
        boolean eligible(long now);
        Page read(String cursor);
        default Capture capture(boolean clock) {if(clock)throw failure(409,"acquisition_clock_source_required");return capture();}
        default Context context(boolean clock) {if(clock)throw failure(409,"acquisition_clock_source_required");return context();}
        default Page read(String cursor,boolean clock) {if(clock)throw failure(409,"acquisition_clock_source_required");return read(cursor);}
    }
    private record Part(String name, byte[] bytes, String hash) { }
    private final LongSupplier clock;
    private final TerrainDispatch dispatch;
    private final Executor client, encoder;
    private final Source source;
    private final Map<TerrainAcquisitionRequest.Owner,byte[]> history = new LinkedHashMap<>();
    private final List<Tracked> encoderTasks = new ArrayList<>();
    private Job current;
    private int admitted;
    private boolean closed;

    private static final class Job {
        final TerrainAcquisitionRequest.Prepare request;
        final TerrainDispatch.Lease lease;
        final long created;
        final Map<String,Part> parts = new LinkedHashMap<>();
        final List<JsonObject> slices = new ArrayList<>();
        String status="preparing", reason, terminalWanted, cursor;
        Long prepared,activated,stopped,released,terminalTurn;
        int clientPending,encodingPending,admissions,turn;
        long lastContextTick,lastClock;
        boolean clockInvalid;
        boolean stop,cancelRequested,finalEncoded,retiring;
        Context context;
        byte[] wrapper;
        JsonObject terminalManifest;
        Job(TerrainAcquisitionRequest.Prepare request,TerrainDispatch.Lease lease,long created) {
            this.request=request;this.lease=lease;this.created=created;this.lastClock=created;
        }
        boolean terminal() { return released!=null; }
    }

    TerrainAcquisition(LongSupplier clock,TerrainDispatch dispatch,Executor client,Executor encoder,Source source) {
        this.clock=clock;this.dispatch=dispatch;this.client=client;this.encoder=encoder;this.source=source;
    }

    /** Called by the existing HTTP worker: it encodes A itself, never waits on another HTTP worker. */
    byte[] prepare(TerrainAcquisitionRequest.Prepare request) throws InterruptedException,ExecutionException,TimeoutException {
        if(request.schema()!=1 && request.schema()!=2)throw failure(400,"acquisition_unsupported_schema");
        final Job job;
        retire();
        synchronized(this) {
            if(closed)throw failure(503,"acquisition_closed");
            if(history.containsKey(request.owner()) || current!=null && current.request.owner().equals(request.owner()))
                throw failure(409,"acquisition_id_already_seen");
            if(current!=null)throw failure(429,"acquisition_busy");
            if(admitted>=MAX_IDENTITIES)throw failure(409,"acquisition_identity_capacity");
            job=new Job(request,dispatch.acquire(),clock.getAsLong()); current=job; admitted++;
            // The current HTTP worker owns A encoding/publication even while waiting for capture.
            job.encodingPending++;
        }
        CompletableFuture<Capture> captured=new CompletableFuture<>();
        boolean preparationWorkHeld=true;
        try {
            submitClient(job,()-> {
                checkOpen(job);
                Capture capture=source.capture(job.request.clock());
                if(capture.context()==null || job.request.clock()!=(capture.context().clock()!=null)
                        || !capture.context().same(source.context(job.request.clock())))throw failure(409,"acquisition_context_changed");
                synchronized(this) { checkOpen(job); job.context=capture.context();job.lastContextTick=capture.context().chronology(); }
                return capture;
            },captured);
            Capture capture=captured.get(remaining(job),TimeUnit.NANOSECONDS);
            byte[] a=encodeBody(capture.body());
            synchronized(this) {checkOpen(job);put(job,"a",a);checkOpen(job);job.prepared=job.lastClock;}
            byte[] wrapper=prepareBytes(job,a);
            synchronized(this) {
                checkOpen(job);job.wrapper=wrapper;bound(job);
                job.status="prepared";job.encodingPending--;preparationWorkHeld=false;settle(job);
                return wrapper.clone();
            }
        } catch(InterruptedException failure) {
            synchronized(this) { stop(job,"acquisition_interrupted","failed"); }
            throw failure;
        } catch(TimeoutException failure) {
            synchronized(this) { stop(job,"acquisition_deadline","failed"); }
            throw failure;
        } catch(ExecutionException failure) {
            synchronized(this) { stop(job,code(failure.getCause(),"acquisition_prepare_failed"),"failed"); }
            throw failure;
        } catch(RuntimeException failure) {
            synchronized(this) { stop(job,code(failure,"acquisition_encoding_failed"),"failed"); }
            throw failure;
        } finally {
            synchronized(this) {
                if(preparationWorkHeld)job.encodingPending--;
                settle(job);
            }
        }
    }

    byte[] activate(TerrainAcquisitionRequest.Activate request) throws InterruptedException,ExecutionException,TimeoutException {
        retire();final Job job;
        synchronized(this) {
            job=require(request.owner());
            if(job.request.schema()!=request.schema())throw failure(409,"acquisition_schema_changed");
            if(!job.status.equals("prepared"))throw failure(409,"acquisition_already_activated");
            checkOpen(job);
            if(!job.parts.get("a").hash.equals(request.aHash())) {
                stop(job,"acquisition_a_hash_changed","failed");throw failure(409,"acquisition_a_hash_changed");
            }
            if(job.clientPending!=0 || job.encodingPending!=0)throw failure(409,"acquisition_work_pending");
            job.status="activating";
        }
        CompletableFuture<Boolean> activated=new CompletableFuture<>();
        try {
            // Capture the original remaining budget before submission: a direct executor or
            // fast real tick can already finish the same job before execute() returns.
            long waitBudget=remaining(job);
            submitClient(job,()-> {
                checkContext(job);
                synchronized(this) { checkOpen(job);job.activated=job.lastClock;job.status="active"; }
                return true;
            },activated);
            activated.get(waitBudget,TimeUnit.NANOSECONDS);
            // A fast native hook may already have completed this same activation.
            // Inspect its valid state; never treat that as permission to activate again.
            synchronized(this) {if(!job.terminal())deadline(job);}
            return manifestBytes(job);
        } catch(InterruptedException failure) {
            synchronized(this) { stop(job,"acquisition_interrupted","failed"); }throw failure;
        } catch(TimeoutException failure) {
            synchronized(this) { stop(job,"acquisition_deadline","failed"); }throw failure;
        } catch(ExecutionException failure) {
            synchronized(this) { stop(job,code(failure.getCause(),"acquisition_activation_failed"),"failed"); }throw failure;
        } catch(RuntimeException failure) {
            synchronized(this) { stop(job,code(failure,"acquisition_activation_failed"),"failed"); }throw failure;
        }
    }

    /** Actual Post-client-tick opportunity. Eligibility is not a scheduling guarantee. */
    void tick() {
        final Job job;
        retire();
        synchronized(this) {
            job=current;
            if(job==null || job.terminal())return;
            deadline(job);
            if(job.stop || job.context==null || job.clientPending!=0)return;
        }
        try {
            checkContext(job); // Check invalidation even while the encoder is pending.
            final long opportunity;
            synchronized(this) {
                checkOpen(job);
                if(!job.status.equals("active") || job.encodingPending!=0)return;
                opportunity=job.lastClock;
            }
            if(!source.eligible(opportunity))return;
            synchronized(this) {
                checkOpen(job);
                if(job.slices.size()>=4){stop(job,"acquisition_page_budget","failed");return;}
                job.clientPending++;job.turn++;
            }
            try {
                checkContext(job);
                final long beforeRead;
                synchronized(this){checkOpen(job);beforeRead=job.lastClock;}
                Page page=source.read(job.cursor,job.request.clock());
                checkContext(job);
                synchronized(this) {
                    checkOpen(job);
                    // These are earlier within-task samples, not new current-clock observations.
                    if(page.actualStart()-beforeRead<0 || page.end()-page.actualStart()<0
                            || job.lastClock-page.end()<0) {
                        job.clockInvalid=true;stop(job,"acquisition_clock_invalid","failed");
                        throw failure(409,"acquisition_clock_invalid");
                    }
                }
                JsonObject body=page.body();
                boolean complete=body.get("complete").getAsBoolean();
                Capture terminal=complete?source.capture(job.request.clock()):null;
                if(terminal!=null && !job.context.same(terminal.context()))throw failure(409,"acquisition_context_changed");
                checkContext(job);
                JsonObject slice=new JsonObject();
                slice.addProperty("index",job.slices.size());slice.addProperty("task_turn",job.turn);
                nano(slice,"start_nano",page.actualStart());nano(slice,"end_nano",page.end());
                for(String key:new String[]{"offset","next_offset","returned"})slice.add(key,body.get(key).deepCopy());
                slice.add("source_tick",body.get("game_time").deepCopy());slice.add("response_tick",body.get("response_game_time").deepCopy());
                if(job.request.clock()) {
                    long sourceCount=ObservationClientClock.wireCount(body.getAsJsonObject("source_clock"),job.context.clock());
                    long responseCount=ObservationClientClock.wireCount(body.getAsJsonObject("response_clock"),job.context.clock());
                    long previous=job.slices.isEmpty()?job.context.clock().count():
                            ObservationClientClock.wireCount(job.slices.get(job.slices.size()-1).getAsJsonObject("response_clock"),job.context.clock());
                    if(sourceCount<previous || responseCount<sourceCount || responseCount>job.lastContextTick)
                        throw failure(409,"acquisition_tick_reversed");
                    slice.add("source_clock",body.get("source_clock").deepCopy());slice.add("response_clock",body.get("response_clock").deepCopy());
                }
                nano(slice,"encode_start_nano",null);nano(slice,"encode_end_nano",null);
                synchronized(this) {
                    checkOpen(job);job.slices.add(slice);
                    if(complete)job.terminalTurn=(long)job.turn;
                    else job.cursor=body.get("next_cursor").getAsString();
                    job.status="encoding";
                }
                submitEncoder(job,body,terminal==null?null:terminal.body(),slice,complete);
            } finally {
                synchronized(this) { job.clientPending--;settle(job); }
            }
        } catch(Throwable failure) {
            synchronized(this) { stop(job,code(failure,"acquisition_capture_failed"),"failed"); }
        }
    }

    byte[] status(TerrainAcquisitionRequest.Owner owner) {
        retire();Job job;
        synchronized(this) {
            job=current;
            if(job==null || !job.request.owner().equals(owner)) {
                byte[] past=history.get(owner);if(past==null)throw failure(404,"acquisition_not_found");return past.clone();
            }
            deadline(job);
        }
        return manifestBytes(job);
    }
    byte[] fetch(TerrainAcquisitionRequest.Fetch request) {
        retire();
        synchronized(this) {
            Job job=require(request.owner());
            // Terminal evidence stays immutable; freshness is a distinct fetch condition.
            long observed=observeClock(job);
            if(job.clockInvalid) {
                if(!job.terminal())stop(job,"acquisition_clock_invalid","failed");
                throw failure(409,"acquisition_clock_invalid");
            }
            if(elapsed(observed,job.created)>=DEADLINE)throw failure(409,"acquisition_deadline");
            deadline(job);
            if(job.stop || !(job.status.equals("prepared") && request.part().equals("a") || job.status.equals("succeeded")))
                throw failure(409,"acquisition_part_unavailable");
            Part part=job.parts.get(request.part());
            if(part==null || !part.hash.equals(request.hash()))throw failure(409,"acquisition_part_mismatch");
            return part.bytes.clone();
        }
    }
    byte[] cancel(TerrainAcquisitionRequest.Cancel request) {
        retire();Job job;
        synchronized(this) {
            job=require(request.owner());
            if(job.request.schema()!=request.schema())throw failure(409,"acquisition_schema_changed");
            if(job.terminal())throw failure(409,"acquisition_already_terminal");
            if(job.cancelRequested)throw failure(409,"acquisition_cancel_already_requested");
            job.cancelRequested=true;stop(job,"acquisition_cancel_requested","cancelled");
        }
        return manifestBytes(job);
    }
    synchronized void transportFailed(TerrainAcquisitionRequest.Owner owner) {
        if(current!=null && current.request.owner().equals(owner) && !current.terminal())
            stop(current,"acquisition_delivery_unknown","failed");
    }
    synchronized void close() {
        closed=true;if(current!=null && !current.terminal())stop(current,"acquisition_closed","failed");
    }
    synchronized void open() {
        if(current!=null && !current.terminal())throw new IllegalStateException("acquisition_owner_still_held");
        closed=false;
    }
    synchronized void removedFromExecutor(List<Runnable> removed) {
        for(Runnable task:removed)if(task instanceof TerrainAcquisition.Tracked tracked && encoderTasks.contains(tracked))tracked.neverStarted();
    }

    private interface Work<T> { T run() throws Exception; }
    private <T> void submitClient(Job job,Work<T> work,CompletableFuture<T> result) {
        synchronized(this) { checkOpen(job);if(job.admissions>=2)throw failure(409,"acquisition_admission_budget");job.admissions++;job.clientPending++; }
        ClientTask<T> task=new ClientTask<>(job,work,result);
        try { client.execute(task); }
        catch(RejectedExecutionException rejected) {
            synchronized(this){task.neverStarted();stop(job,"acquisition_client_rejected","failed");}
            result.completeExceptionally(rejected);
        }
        catch(RuntimeException unknown) {
            // An arbitrary executor exception is not proof that its queued callback cannot run.
            synchronized(this){stop(job,"acquisition_submission_unknown","failed");}
            result.completeExceptionally(unknown);
        }
    }
    private final class ClientTask<T> implements Runnable {
        final Job job;final Work<T> work;final CompletableFuture<T> result;boolean started,done;
        ClientTask(Job job,Work<T> work,CompletableFuture<T> result){this.job=job;this.work=work;this.result=result;}
        @Override public void run() {
            synchronized(TerrainAcquisition.this){if(done)return;started=true;}
            T value=null;Throwable error=null;
            try {checkOpen(job);value=work.run();}
            catch(Throwable failure){error=failure;synchronized(TerrainAcquisition.this){stop(job,code(failure,"acquisition_client_failed"),"failed");}}
            finally{synchronized(TerrainAcquisition.this){finish();}}
            if(error==null)result.complete(value);else result.completeExceptionally(error);
        }
        void neverStarted(){if(!started&&!done)finish();}
        void finish(){if(done)return;done=true;job.clientPending--;settle(job);}
    }
    private void submitEncoder(Job job,JsonObject page,JsonObject terminal,JsonObject slice,boolean complete) {
        Tracked task=new Tracked(job,()-> {
            synchronized(this){checkOpen(job);nano(slice,"encode_start_nano",job.lastClock);}
            byte[] pageBytes=encodeBody(page), cBytes=terminal==null?null:encodeBody(terminal);
            synchronized(this) {
                checkOpen(job);nano(slice,"encode_end_nano",job.lastClock);
                put(job,"p"+slice.get("index").getAsInt(),pageBytes);
                if(cBytes!=null)put(job,"c",cBytes);
                job.finalEncoded=complete;
                if(!complete && job.slices.size()==4)stop(job,"acquisition_page_budget","failed");
                else job.status=complete?"encoding":"active";
                bound(job);
            }
        });
        synchronized(this){checkOpen(job);job.encodingPending++;encoderTasks.add(task);}
        try {encoder.execute(task);}
        catch(RejectedExecutionException rejected){synchronized(this){task.neverStarted();stop(job,"acquisition_encoder_rejected","failed");}}
        catch(RuntimeException unknown){synchronized(this){stop(job,"acquisition_submission_unknown","failed");}}
    }
    private final class Tracked implements Runnable {
        final Job job;final Runnable work;boolean started,done;
        Tracked(Job job,Runnable work){this.job=job;this.work=work;}
        @Override public void run() {
            synchronized(TerrainAcquisition.this){if(done)return;started=true;}
            try {checkOpen(job);work.run();}
            catch(Throwable failure){synchronized(TerrainAcquisition.this){stop(job,code(failure,"acquisition_encoding_failed"),"failed");}}
            finally {synchronized(TerrainAcquisition.this){finish();}}
        }
        void neverStarted(){if(!started&&!done)finish();}
        void finish(){if(done)return;done=true;encoderTasks.remove(this);job.encodingPending--;settle(job);}
    }
    private void checkContext(Job job) {
        checkOpen(job);Context actual=source.context(job.request.clock());
        if(job.context==null || !job.context.same(actual))throw failure(409,"acquisition_context_changed");
        synchronized(this) {
            checkOpen(job);
            if(actual.chronology()<job.lastContextTick)throw failure(409,"acquisition_tick_reversed");
            job.lastContextTick=actual.chronology();
        }
    }
    private synchronized void checkOpen(Job job) {
        deadline(job);
        if(current!=job || job.stop || job.terminal() || closed)throw failure(409,job.reason==null?"acquisition_not_active":job.reason);
    }
    private long remaining(Job job) {
        synchronized(this){checkOpen(job);long remaining=DEADLINE-elapsed(job.lastClock,job.created);if(remaining<=0)throw failure(409,"acquisition_deadline");return remaining;}
    }
    private Job require(TerrainAcquisitionRequest.Owner owner) {
        if(current==null || !current.request.owner().equals(owner))throw failure(404,"acquisition_not_found");return current;
    }
    private void deadline(Job job) {
        if(job.terminal())return;
        long age=observeClock(job)-job.created;
        if(job.clockInvalid || age<0)stop(job,"acquisition_clock_invalid","failed");
        else if(age>=DEADLINE)stop(job,"acquisition_deadline","failed");
    }
    /** Call only under this monitor: never compare samples acquired by racing threads off-lock. */
    private long observeClock(Job job) {
        long now=clock.getAsLong();
        if(now-job.lastClock<0)job.clockInvalid=true;
        job.lastClock=now; // Preserve the actual sample, including an invalid one; never clamp.
        return now;
    }
    static long elapsed(long now,long origin) {
        long age=now-origin;if(age<0)throw failure(409,"acquisition_clock_invalid");return age;
    }
    private void stop(Job job,String reason,String terminal) {
        if(job.terminal())return;
        if(!job.stop){job.stop=true;job.reason=reason;job.terminalWanted=terminal;}
        job.status="stopping";settle(job);
    }
    private void settle(Job job) {
        if(job.terminal() || job.clientPending!=0 || job.encodingPending!=0)return;
        if(!job.stop && !job.finalEncoded)return;
        job.stopped=observeClock(job);
        job.lease.close();
        job.released=observeClock(job);
        if(!job.stop) {
            long age=job.released-job.created;
            if(job.clockInvalid || age<0 || age>=DEADLINE) {
                job.stop=true;job.reason=job.clockInvalid || age<0?"acquisition_clock_invalid":"acquisition_deadline";
                job.terminalWanted="failed";
            }
        }
        job.status=job.stop?job.terminalWanted:"succeeded";
        // Immutable terminal metadata is frozen at actual release, never reconstructed from later clocks/history.
        job.terminalManifest=manifest(job,payloadBytes(job));
    }
    private void put(Job job,String name,byte[] bytes) {
        if(bytes.length>RESPONSE_LIMIT)throw failure(500,"acquisition_response_too_large");
        if(job.parts.containsKey(name))throw failure(409,"acquisition_duplicate_part");
        job.parts.put(name,new Part(name,bytes,hash(bytes)));bound(job);
    }
    private int payloadBytes(Job job) {
        int count=history.values().stream().mapToInt(b->b.length).sum();
        for(Part part:job.parts.values())count+=part.bytes.length;
        if(job.wrapper!=null)count+=job.wrapper.length;return count;
    }
    private void bound(Job job) {
        if(payloadBytes(job)>RETAINED_LIMIT)throw failure(500,"acquisition_retention_limit");
    }
    private byte[] prepareBytes(Job job,byte[] a) {
        final JsonObject frame;final int payload;
        synchronized(this) {
            checkOpen(job);frame=manifest(job,0);payload=payloadBytes(job);
            // Detached prospective metadata; publish only after encoding and guarded commit.
            frame.addProperty("status","prepared");frame.addProperty("encoding_pending",false);
        }
        String prefix="{\"ok\":true,\"protocol\":\"mineclient-bridge\",\"schema_version\":2,\"acquisition_schema_version\":"+job.request.schema()+",\"acquisition\":"
                +METADATA.toJson(job.request.clock()?TerrainAcquisitionRequest.CLOCK_VERSION:TerrainAcquisitionRequest.VERSION)+",\"job_id\":"
                +METADATA.toJson(job.request.owner().jobId())+",\"owner_id\":"+METADATA.toJson(job.request.owner().ownerId())+",\"a\":";
        String base=prefix+new String(a,StandardCharsets.UTF_8)+",\"manifest\":";
        int total=payload;
        for(int i=0;i<4;i++) {
            frame.addProperty("retained_bytes",total);byte[] manifest=metadata(frame);
            if(manifest.length>MANIFEST_LIMIT)throw failure(500,"acquisition_manifest_too_large");
            byte[] result=(base+new String(manifest,StandardCharsets.UTF_8)+"}").getBytes(StandardCharsets.UTF_8);
            if(result.length>RESPONSE_LIMIT)throw failure(500,"acquisition_response_too_large");
            int actual=payload+result.length;
            if(actual==total)return result;total=actual;
        }
        throw failure(500,"acquisition_size_accounting_unstable");
    }
    private JsonObject manifest(Job job,int retained) {
        JsonObject result=base(job);
        result.addProperty("status",job.status);nullable(result,"reason",job.reason);
        result.addProperty("stop_requested",job.stop);result.addProperty("admission_held",!job.terminal());
        result.addProperty("client_work_pending",job.clientPending!=0);result.addProperty("encoding_pending",job.encodingPending!=0);
        result.addProperty("request_admissions",job.admissions);
        nano(result,"created_nano",job.created);nano(result,"deadline_nano",job.created+DEADLINE);
        nano(result,"prepared_nano",job.prepared);nano(result,"activated_nano",job.activated);
        nano(result,"stopped_nano",job.stopped);nano(result,"released_nano",job.released);
        JsonObject context=job.context==null?null:job.context.wire().deepCopy();
        if(context!=null && job.request.clock())context.add("observation_clock_domain",job.context.clock().domain());
        if(context!=null){if(job.request.defenseEpoch()==null)context.add("defense_epoch",JsonNull.INSTANCE);else context.addProperty("defense_epoch",job.request.defenseEpoch());}
        result.add("context",context==null?JsonNull.INSTANCE:context);
        JsonArray parts=new JsonArray();
        for(Part part:job.parts.values()){JsonObject row=new JsonObject();row.addProperty("part",part.name);row.addProperty("sha256",part.hash);row.addProperty("bytes",part.bytes.length);parts.add(row);}
        result.add("parts",parts);JsonArray slices=new JsonArray();for(JsonObject slice:job.slices)slices.add(slice.deepCopy());result.add("slices",slices);
        if(job.terminalTurn==null)result.add("terminal_task_turn",JsonNull.INSTANCE);else result.addProperty("terminal_task_turn",job.terminalTurn);
        result.addProperty("retained_bytes",retained);return result;
    }
    private byte[] manifestBytes(Job job) {
        for(int attempt=0;attempt<4;attempt++) {
            final JsonObject frame;final boolean terminal;
            synchronized(this) {
                terminal=job.terminal();
                frame=terminal?job.terminalManifest.deepCopy():manifest(job,payloadBytes(job));
            }
            byte[] bytes=metadata(frame);
            if(bytes.length>MANIFEST_LIMIT)throw failure(500,"acquisition_manifest_too_large");
            synchronized(this) {
                // A detached pending view cannot advertise usable preparation after stop or closure.
                // Re-encoding metadata is bounded inspection, never a replay of native acquisition.
                if(!terminal && (job.stop!=frame.get("stop_requested").getAsBoolean()
                        || job.terminal() || (frame.get("status").getAsString().equals("prepared")
                        && !job.status.equals("prepared"))))continue;
                return bytes;
            }
        }
        throw failure(409,"acquisition_status_changed");
    }
    private JsonObject base(Job job) {
        JsonObject result=new JsonObject();result.addProperty("ok",true);result.addProperty("protocol","mineclient-bridge");
        result.addProperty("schema_version",2);result.addProperty("acquisition_schema_version",job.request.schema());
        result.addProperty("acquisition",job.request.clock()?TerrainAcquisitionRequest.CLOCK_VERSION:TerrainAcquisitionRequest.VERSION);
        result.addProperty("job_id",job.request.owner().jobId());result.addProperty("owner_id",job.request.owner().ownerId());return result;
    }
    private void retire() {
        final Job job;final JsonObject tombstone;final int prior;
        synchronized(this) {
            job=current;if(job==null || !job.terminal() || job.retiring)return;
            long observed=observeClock(job);
            long age=observed-job.released;if(job.clockInvalid || age<0 || age<RETENTION)return;
            job.retiring=true;tombstone=base(job);
            tombstone.addProperty("status","expired");tombstone.addProperty("original_status",job.status);
            nullable(tombstone,"reason",job.reason);tombstone.addProperty("stop_requested",job.stop);
            tombstone.addProperty("admission_held",false);tombstone.addProperty("client_work_pending",false);tombstone.addProperty("encoding_pending",false);
            tombstone.addProperty("request_admissions",job.admissions);nano(tombstone,"created_nano",job.created);nano(tombstone,"stopped_nano",job.stopped);
            nano(tombstone,"released_nano",job.released);nano(tombstone,"expired_nano",observed);
            prior=history.values().stream().mapToInt(b->b.length).sum();
        }
        try {
            int total=prior;byte[] bytes=null;boolean stable=false;
            for(int i=0;i<4;i++) {
                tombstone.addProperty("retained_bytes",total);bytes=metadata(tombstone);int next=prior+bytes.length;
                if(next==total){stable=true;break;}total=next;
            }
            if(!stable || bytes.length>4096 || total>RETAINED_LIMIT)throw failure(500,"acquisition_retention_limit");
            synchronized(this){if(current==job){history.put(job.request.owner(),bytes);current=null;}}
        } finally {synchronized(this){job.retiring=false;}}
    }
    private static byte[] encodeBody(JsonObject body) {
        try {byte[] bytes=BridgeJson.toJson(body).getBytes(StandardCharsets.UTF_8);if(bytes.length>RESPONSE_LIMIT)throw failure(500,"acquisition_response_too_large");return bytes;}
        catch(IOException failure){throw failure(500,"acquisition_encoding_failed");}
    }
    private static byte[] metadata(JsonObject value){return METADATA.toJson(value).getBytes(StandardCharsets.UTF_8);}
    static String hash(byte[] bytes) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
        catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
    private static void nano(JsonObject object,String field,Long value){if(value==null)object.add(field,JsonNull.INSTANCE);else object.addProperty(field,Long.toString(value));}
    private static void nullable(JsonObject object,String field,String value){if(value==null)object.add(field,JsonNull.INSTANCE);else object.addProperty(field,value);}
    private static String code(Throwable failure,String fallback){return failure instanceof TerrainScan.Failure?failure.getMessage():failure instanceof ClientActionRequest.Rejected?failure.getMessage():failure instanceof ObservationClientClock.Unavailable?failure.getMessage():fallback;}
    private static TerrainScan.Failure failure(int status,String code){return TerrainAcquisitionRequest.failure(status,code);}
}
