import com.google.gson.*;
import finite.Trace;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.function.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.*;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Finite adapter fixtures. No game, registry bootstrap, physics, network, or timing benchmark. */
public final class FiniteAdapterChecks {
 static final Gson GSON=new GsonBuilder().setPrettyPrinting().serializeNulls().create();
 static Class<?> legacy,candidate,queryType;
 static int assertions,rawCases,wrapperCases;
 static final List<Object> results=new ArrayList<>(),differences=new ArrayList<>(),failures=new ArrayList<>();
 static final Set<String> groups=new LinkedHashSet<>();
 static final TerrainReaderDifferentialOracle.Position ORIGIN=new TerrainReaderDifferentialOracle.Position(0,64,0);
 static final class Fixture implements TerrainReaderDifferentialOracle.Fixture {
  final Minecraft mc=new Minecraft(); final ClientLevel world=new ClientLevel(); final BlockState state=new BlockState(),air=new BlockState();
  Fixture(Consumer<Fixture> setup){Trace.reset();mc.level=world;mc.player=new Minecraft.Player();Minecraft.instance=mc;
   air.label="fallback";air.block=Blocks.AIR;air.air=true;air.shape.empty=true;air.shape.topFull=false;air.fluid.label="fallbackFluid";Blocks.AIR.defaultState=air;
   world.chunks.chunk=new LevelChunk(p->state);setup.accept(this);
  }
  public Object minecraft(){return mc;} public List<String> trace(){return Trace.events;} public void clearTrace(){Trace.events.clear();}
 }
 interface Checked { void run() throws Exception; }
 interface Verify { void check(TerrainReaderDifferentialOracle.Observation o) throws Exception; }
 static void eq(Object a,Object b,String why){assertions++;if(!Objects.equals(a,b))throw new AssertionError(why+" expected="+a+" actual="+b);}
 static void yes(boolean value,String why){assertions++;if(!value)throw new AssertionError(why);}
 static String failureType(TerrainReaderDifferentialOracle.Observation o){return o.thrown()==null?null:o.thrown().type();}
 static void metric(TerrainReaderDifferentialOracle.Observation o,String k,long v){eq(v,o.metrics().get(k),"metric "+k);}
 static long count(List<String> trace,String prefix){return trace.stream().filter(s->s.startsWith(prefix)).count();}
 static void run(String group,String name,Checked work){groups.add(group);try{work.run();}catch(Throwable e){failures.add(Map.of("group",group,"case",name,"error",e.toString()));System.err.println("FAIL "+name+" "+e);}}
 static void raw(String group,String name,Consumer<Fixture> setup,Verify verify){raw(group,name,setup,ORIGIN,verify);}
 static void raw(String group,String name,Consumer<Fixture> setup,TerrainReaderDifferentialOracle.Position p,Verify verify){
  run(group,name,()->{
   var observations=new ArrayList<TerrainReaderDifferentialOracle.Observation>();
   observations.add(TerrainReaderDifferentialOracle.observe(legacy,c->new Fixture(setup),p,false,false));
   observations.add(TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(setup),p,false,false));
   observations.add(TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(setup),p,true,false));
   observations.add(TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(setup),p,true,true));
   rawCases++;results.add(Map.of("kind","four_path_adapter","group",group,"case",name,"observations",observations));
   var old=observations.get(0);var measured=observations.get(3);
   eq(old.json(),observations.get(1).json(),name+" complete JSON including omitted/null keys");
   for(int i=1;i<4;i++){var actual=observations.get(i);
    eq(old.cell(),actual.cell(),name+" all seven typed Cell fields path "+i);
    eq(failureType(old),failureType(actual),name+" raw failure class path "+i);
    eq(old.trace(),actual.trace(),name+" ordered callback trace path "+i);
    if(!Objects.equals(old.thrown(),actual.thrown()))differences.add(Map.of("case",name,"path",i,"kind","raw_exception_message","legacy",old.thrown(),"candidate",actual.thrown()));
   }
   for(var m:measured.metrics().entrySet())yes(m.getValue()>=0,name+" nonnegative "+m.getKey());
   verify.check(old);verifyMetrics(measured,name,p);
  });
 }
 static void verifyMetrics(TerrainReaderDifferentialOracle.Observation o,String name,TerrainReaderDifferentialOracle.Position p){
  eq(count(o.trace(),"chunk.getBlockState:"),o.metrics().get("stateReads"),name+" measured state callbacks");
  eq(count(o.trace(),"state.getFluidState")+count(o.trace(),"fallback.getFluidState"),o.metrics().get("fluidReads"),name+" measured fluid callbacks");
  eq(count(o.trace(),"chunks.getChunk:"),o.metrics().get("chunkFetches"),name+" measured fetch callbacks");
  eq(o.metrics().get("chunkRequests"),o.metrics().get("chunkFetches")+o.metrics().get("chunkCacheHits"),name+" cache accounting");
 }
 static void failure(TerrainReaderDifferentialOracle.Observation o,String type){eq(type,failureType(o),"expected raw failure");eq(null,o.cell(),"no successful Cell");eq(null,o.json(),"no successful JSON");eq(0L,count(o.trace(),"state.getCollisionShape"),"no collision after metadata failure");}
 static void known(TerrainReaderDifferentialOracle.Observation o){eq(null,o.thrown(),"no exception");eq("LOADED",o.cell().availability(),"loaded");eq(true,o.cell().collisionKnown(),"collision known");eq(false,o.json().get("hazards_exhaustive").getAsBoolean(),"nonexhaustive hazards");}
 static void unknown(TerrainReaderDifferentialOracle.Observation o,String reason){eq(null,o.thrown(),"unknown collision is not metadata failure");eq(false,o.cell().collisionKnown(),"collision unknown");eq(false,o.cell().collisionEmpty(),"no partial empty fact");eq(false,o.cell().fullTopSupport(),"no partial support fact");eq(reason,o.json().get("collision_unknown_reason").getAsString(),"unknown cause");for(String key:List.of("collision_bounds","collision_empty","full_top_support"))yes(!o.json().has(key),"unknown omits "+key);}
 static void addProp(Fixture f,String name,String value){f.state.values.put(new Property<String>(name,value),"raw");}
 static void hazards(TerrainReaderDifferentialOracle.Observation o,String... labels){known(o);eq(GSON.toJsonTree(labels),o.json().get("hazards"),"ordered hazards");eq(labels.length>0,o.cell().hazardous(),"typed hazard");}
 static void rawCases(){
  raw("dry_full_support","dry_full_support",f->{},o->{known(o);eq(new TerrainReaderDifferentialOracle.CellView("LOADED","minecraft:stone",true,false,true,"minecraft:empty",false),o.cell(),"complete stone Cell");JsonObject expected=JsonParser.parseString("{\"known\":true,\"id\":\"minecraft:stone\",\"id_truncated\":false,\"air\":false,\"properties\":{},\"properties_truncated\":false,\"fluid\":\"minecraft:empty\",\"fluid_truncated\":false,\"fluid_source\":false,\"hazards\":[],\"hazards_exhaustive\":false,\"collision_known\":true,\"collision_empty\":false,\"full_top_support\":true,\"collision_bounds\":[0,0,0,1,1,1]}").getAsJsonObject();eq(expected,o.json(),"complete expected JSON");});
  raw("dry_air","dry_air",f->{f.state.air=true;f.state.block.id="minecraft:air";f.state.shape.empty=true;},o->{known(o);eq(true,o.cell().collisionEmpty(),"empty");eq(false,o.cell().fullTopSupport(),"empty has no top face");yes(!o.json().has("collision_bounds"),"empty omits bounds");eq(0L,count(o.trace(),"Block.isFaceFull"),"empty bypasses face hook");});
  for(boolean top:List.of(false,true))raw("partial_collision","configured_partial_top_"+top,f->{f.state.shape.box=new AABB(0,0,0,1,.5,1);f.state.shape.topFull=top;},o->{known(o);eq(top,o.cell().fullTopSupport(),"propagate face callback; no physics inference");eq(.5,o.json().getAsJsonArray("collision_bounds").get(4).getAsDouble(),"partial bound");});
  raw("missing_chunk","missing_chunk",f->f.world.chunks.missing=true,o->{eq("UNLOADED",o.cell().availability(),"unloaded");eq(null,o.json(),"no loaded JSON");eq(0L,count(o.trace(),"chunk.getBlockState:"),"no unloaded block access");yes(o.trace().contains("chunks.getChunk:0,0,FULL,false"),"load only");});
  for(int y:new int[]{-65,-64,319,320})raw("height_limits","height_"+y,f->{},new TerrainReaderDifferentialOracle.Position(0,y,0),o->{boolean inside=y>=-64&&y<320;eq(inside?"LOADED":"OUT_OF_WORLD",o.cell().availability(),"height boundary");if(!inside)eq(0L,count(o.trace(),"chunks.getChunk:"),"height checked before chunks");});
  for(int x:new int[]{-1,-16,-17})raw("negative_chunk_coordinates","negative_"+x,f->{},new TerrainReaderDifferentialOracle.Position(x,64,x),o->{known(o);yes(o.trace().contains("chunks.getChunk:"+(x>>4)+","+(x>>4)+",FULL,false"),"signed shift coordinates");});
  for(int length:new int[]{160,161})raw("identifier_160_161","identifier_"+length,f->{f.state.block.id="m:"+"x".repeat(length-2);f.state.fluid.type.id="m:"+"f".repeat(length-2);},o->{known(o);eq(160,o.cell().id().length(),"block bounded");eq(160,o.cell().fluid().length(),"fluid bounded");eq(length>160,o.json().get("id_truncated").getAsBoolean(),"block truncation");eq(length>160,o.json().get("fluid_truncated").getAsBoolean(),"fluid truncation");});
  raw("properties_first_eight_visited","first_eight_visited",f->{addProp(f,"invalid name","ok");for(int n=2;n<=9;n++)addProp(f,"p"+n,"ok");Trace.failures.add("property.value:p9");},o->{known(o);eq(Set.of("p2","p3","p4","p5","p6","p7","p8"),o.json().getAsJsonObject("properties").keySet(),"first eight visited");eq(8L,count(o.trace(),"property.value:"),"eight callbacks including invalid name");eq(2L,count(o.trace(),"state.getValues:"),"two getValues calls");eq(true,o.json().get("properties_truncated").getAsBoolean(),"truncated");});
  String[] texts={"a".repeat(32),"a".repeat(33),"a b","quote\"","line\n","","a_A.0:/-"};
  for(int i=0;i<texts.length;i++)for(boolean inName:List.of(false,true)){String text=texts[i];boolean accepted=i==0||i==6;raw("property_regex_boundaries","regex_"+i+"_name_"+inName,f->addProp(f,inName?text:"p",inName?"ok":text),o->{known(o);eq(accepted?1:0,o.json().getAsJsonObject("properties").size(),"regex acceptance");eq(!accepted,o.json().get("properties_truncated").getAsBoolean(),"regex truncation");eq(1L,count(o.trace(),"property.value:"),"value callback even invalid name");});}
  for(String hook:List.of("state.getValues:1","state.getValues:2","property.name:p","property.value:p"))raw("property_failure_positions",hook,f->{addProp(f,"p","v");Trace.failures.add(hook);},o->failure(o,"java.lang.IllegalStateException"));
  raw("property_failure_positions","null_property_name",f->addProp(f,null,"v"),o->failure(o,"java.lang.NullPointerException"));
  raw("property_failure_positions","null_property_value",f->addProp(f,"p",null),o->failure(o,"java.lang.NullPointerException"));
  raw("property_failure_positions","null_values_map",f->f.state.values=null,o->failure(o,"java.lang.NullPointerException"));
  raw("property_failure_positions","ninth_property_failure_unreached",f->{for(int n=1;n<=9;n++)addProp(f,"p"+n,"v");Trace.failures.add("property.value:p9");},o->{known(o);eq(0L,count(o.trace(),"property.value:p9"),"ninth callback not reached");});
  for(String hook:List.of("state.isAir","fluid.isSource"))raw("unused_metadata_hooks_preserved",hook,f->Trace.failures.add(hook),o->failure(o,"java.lang.IllegalStateException"));
  for(String hook:List.of("state.getFluidState","fluid.getType","FLUID.getKey","fluid.is:lava","fluid.is:water"))raw("fluid_hooks_fail_closed",hook,f->Trace.failures.add(hook),o->failure(o,"java.lang.IllegalStateException"));
  raw("fluid_hooks_fail_closed","null_fluid_state",f->f.state.fluid=null,o->failure(o,"java.lang.NullPointerException"));
  raw("fluid_hooks_fail_closed","null_fluid_key",f->f.state.fluid.type.id=null,o->failure(o,"java.lang.NullPointerException"));
  for(int mask=0;mask<4;mask++){int m=mask;raw("hazards_tags","tags_"+mask,f->{f.state.fluid.lava=(m&1)!=0;f.state.fluid.water=(m&2)!=0;},o->hazards(o,m==0?new String[]{}:m==1?new String[]{"lava"}:m==2?new String[]{"water"}:new String[]{"lava","water"}));}
  for(String id:List.of("fire","soul_fire","cactus","magma_block","sweet_berry_bush","wither_rose"))raw("hazards_contact","contact_"+id,f->f.state.block.id="minecraft:"+id,o->hazards(o,"contact_damage"));
  for(String id:List.of("campfire","soul_campfire"))for(String variant:List.of("absent","false","true","throws","null"))raw("hazards_conditional",id+"_"+variant,f->{f.state.block.id="minecraft:"+id;f.state.hasLit=!variant.equals("absent");f.state.lit=variant.equals("null")?null:variant.equals("true");if(variant.equals("throws"))Trace.failures.add("state.getValue:lit");},o->{if(variant.equals("throws")||variant.equals("null"))failure(o,variant.equals("null")?"java.lang.NullPointerException":"java.lang.IllegalStateException");else hazards(o,variant.equals("true")?new String[]{"contact_damage"}:new String[]{});if(variant.equals("absent"))eq(0L,count(o.trace(),"state.getValue:"),"absent lit not read");else yes(o.trace().indexOf("state.hasProperty:lit")<o.trace().indexOf("state.getValue:lit"),"has before get");});
  for(String id:List.of("powder_snow","cobweb","ordinary"))raw("hazards_slow_and_powder",id,f->f.state.block.id="minecraft:"+id,o->hazards(o,id.equals("ordinary")?new String[]{}:new String[]{id.equals("cobweb")?"slowdown":"powder_snow"}));
  raw("hazards_tags","ordered_lava_water_contact",f->{f.state.block.id="minecraft:fire";f.state.fluid.lava=true;f.state.fluid.water=true;},o->hazards(o,"lava","water","contact_damage"));
  for(String hook:List.of("state.getCollisionShape:0,64,0","shape.isEmpty","Block.isFaceFull:UP","shape.bounds"))raw("shape_stage_failures",hook,f->Trace.failures.add(hook),o->unknown(o,"block_shape_failed"));
  raw("shape_stage_failures","null_shape",f->f.state.shape=null,o->unknown(o,"block_shape_failed"));
  raw("shape_stage_failures","null_bounds",f->f.state.shape.box=null,o->unknown(o,"block_shape_failed"));
  for(int axis=0;axis<6;axis++)for(double value:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY}){int a=axis;raw("nonfinite_bounds_all_axes","nonfinite_"+a+"_"+value,f->{double[] d={0,0,0,1,1,1};d[a]=value;f.state.shape.box=new AABB(d[0],d[1],d[2],d[3],d[4],d[5]);},o->unknown(o,"block_shape_failed"));}
  raw("shape_context_identity","identity_and_height",f->f.state.hook=(g,p,c)->{if(g.getHeight()!=384||g.getMinBuildHeight()!=-64)throw new AssertionError("height delegation");},o->{known(o);yes(o.trace().contains("shape.context:bounded=true,same_player=true"),"bounded getter and player identity");});
  for(int[] off:new int[][]{{1,1,1},{-1,-1,-1},{2,0,0},{0,-2,0},{0,0,2}}){boolean permitted=Math.abs(off[0])<=1&&Math.abs(off[1])<=1&&Math.abs(off[2])<=1;raw("shape_context_neighborhood","offset_"+Arrays.toString(off),f->f.state.hook=(g,p,c)->g.getBlockState(new BlockPos(p.x()+off[0],p.y()+off[1],p.z()+off[2])),o->{if(permitted)known(o);else unknown(o,"unavailable_shape_context");eq(permitted?2L:1L,count(o.trace(),"chunk.getBlockState:"),"only permitted context state reads");});}
  raw("shape_context_missing_or_height","context_missing_adjacent",f->{f.world.chunks.missingKeys.add("-1,0");f.state.hook=(g,p,c)->g.getBlockState(new BlockPos(-1,64,0));},o->{unknown(o,"unavailable_shape_context");eq(1L,count(o.trace(),"chunk.getBlockState:"),"missing context not read");});
  for(int y:new int[]{-64,319})raw("shape_context_missing_or_height","context_height_"+y,f->f.state.hook=(g,p,c)->g.getBlockState(new BlockPos(0,y+(y==-64?-1:1),0)),new TerrainReaderDifferentialOracle.Position(0,y,0),o->{unknown(o,"unavailable_shape_context");eq(1L,count(o.trace(),"chunk.getBlockState:"),"out of height context not read");});
  for(int[] calls:new int[][]{{64,0},{65,0},{32,32},{32,33}})raw("shape_context_read_budget","budget_"+calls[0]+"_"+calls[1],f->f.state.hook=(g,p,c)->{for(int n=0;n<calls[0];n++)g.getBlockState(p);for(int n=0;n<calls[1];n++)g.getFluidState(p);},o->{if(calls[0]+calls[1]==64)known(o);else unknown(o,"unavailable_shape_context");eq(65L,count(o.trace(),"chunk.getBlockState:"),"64 permitted context reads plus origin");});
  raw("shape_context_block_entity","context_block_entity",f->f.state.hook=(g,p,c)->{if(g.getBlockEntity(p)!=null)throw new AssertionError("block entity exposed");},o->unknown(o,"unavailable_shape_context"));
  raw("shape_context_then_throw","context_unknown_then_throw",f->f.state.hook=(g,p,c)->{g.getBlockEntity(p);throw new IllegalStateException("after unavailable");},o->unknown(o,"block_shape_failed"));
  raw("context_fluid_counters","context_fluid_permit_deny",f->f.state.hook=(g,p,c)->{g.getFluidState(p);g.getFluidState(new BlockPos(p.x()+2,p.y(),p.z()));},o->unknown(o,"unavailable_shape_context"));
  for(String hook:List.of("chunks.getChunk:0,0,FULL,false","chunk.getBlockState:0,64,0","property.value:p","state.getFluidState","state.getCollisionShape:0,64,0"))raw("metrics_failures","metric_failure_"+hook,f->{addProp(f,"p","v");Trace.failures.add(hook);},o->{if(hook.startsWith("state.getCollisionShape"))unknown(o,"block_shape_failed");else failure(o,"java.lang.IllegalStateException");});
 }
 static Object call(Class<?> type,Object target,String name,Object... args) throws Exception {
  for(Method m:type.getDeclaredMethods()){if(!m.getName().equals(name)||m.getParameterCount()!=args.length)continue;boolean ok=true;Class<?>[] ps=m.getParameterTypes();for(int i=0;i<ps.length;i++){Class<?> p=ps[i];if(p==int.class)p=Integer.class;if(p==double.class)p=Double.class;if(p==boolean.class)p=Boolean.class;if(args[i]!=null&&!p.isInstance(args[i]))ok=false;}if(ok){m.setAccessible(true);try{return m.invoke(target,args);}catch(InvocationTargetException e){if(e.getCause() instanceof Exception x)throw x;throw e;}}}throw new NoSuchMethodException(type+"."+name);
 }
 static Class<?> nested(Class<?> outer,String name){return Arrays.stream(outer.getDeclaredClasses()).filter(c->c.getSimpleName().equals(name)).findFirst().orElseThrow();}
 static Object construct(Class<?> type)throws Exception{var c=type.getDeclaredConstructor();c.setAccessible(true);return c.newInstance();}
 static Object field(Object value,String name)throws Exception{var f=value.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(value);}
 static Object source(Fixture f,Object metrics)throws Exception{return metrics==null?call(candidate,null,"flatCellSource",f.mc):call(candidate,null,"flatCellSource",f.mc,metrics);}
 static Object cell(Object source,int x,int y,int z)throws Exception{return call(source.getClass(),source,"read",x,y,z);}
 static JsonObject page(Class<?> reader,String q)throws Exception{Thread.sleep(60);return (JsonObject)call(reader,null,"read",call(queryType,null,"parse",q));}
 static void wrapper(String group,String name,Checked work){run(group,name,()->{wrapperCases++;work.run();results.add(Map.of("kind","wrapper_or_metrics","group",group,"case",name,"passed",true));});}
 static void expectException(String type,String message,Checked work)throws Exception{try{work.run();throw new AssertionError("Expected "+type+":"+message);}catch(Exception e){eq(type,e.getClass().getName(),"exception type");eq(message,e.getMessage(),"exception message");}}
 static JsonObject normalizedPage(JsonObject page){JsonObject result=page.deepCopy();for(String key:List.of("world_generation","generation","read_elapsed_micros"))result.remove(key);if(result.has("next_cursor")&&!result.get("next_cursor").isJsonNull()){String cursor=result.get("next_cursor").getAsString();result.addProperty("next_cursor","<generation>:"+cursor.substring(cursor.indexOf(':')+1));}return result;}
 static void wrapperCases(){
  wrapper("metrics_loaded_no_context","metrics_loaded_seed",()->{var o=TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(f->{}),ORIGIN,true,true);metric(o,"loadedCellReads",1);metric(o,"stateReads",1);metric(o,"fluidReads",1);metric(o,"chunkRequests",2);metric(o,"chunkFetches",1);metric(o,"chunkCacheHits",1);metric(o,"shapeContextReads",0);for(String k:List.of("stateReadNanos","metadataPreflightNanos","fluidHazardNanos","collisionNanos"))yes(o.metrics().get(k)>=0,"timer scope nonnegative");});
  wrapper("missing_chunk","metrics_unloaded_seed",()->{var o=TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(f->f.world.chunks.missing=true),ORIGIN,true,true);metric(o,"loadedCellReads",0);metric(o,"stateReads",0);metric(o,"fluidReads",0);metric(o,"chunkRequests",1);metric(o,"chunkFetches",1);metric(o,"chunkCacheHits",0);});
  wrapper("height_limits","metrics_out_of_world_seed",()->{var o=TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(f->{}),new TerrainReaderDifferentialOracle.Position(0,320,0),true,true);for(var v:o.metrics().values())eq(0L,v,"out-of-world all counters/timers zero");});
  wrapper("context_fluid_counters","metrics_context_fluid_seed",()->{var o=TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(f->f.state.hook=(g,p,ctx)->{g.getFluidState(p);g.getFluidState(new BlockPos(2,64,0));}),ORIGIN,true,true);metric(o,"fluidReads",3);metric(o,"shapeContextReads",2);metric(o,"stateReads",2);metric(o,"chunkRequests",4);metric(o,"chunkFetches",1);metric(o,"chunkCacheHits",3);});
  wrapper("metrics_failures","metrics_state_throw_seed",()->{var o=TerrainReaderDifferentialOracle.observe(candidate,c->new Fixture(f->Trace.failures.add("chunk.getBlockState:0,64,0")),ORIGIN,true,true);metric(o,"loadedCellReads",1);metric(o,"stateReads",1);metric(o,"fluidReads",0);metric(o,"metadataPreflightNanos",0);metric(o,"collisionNanos",0);});
  wrapper("chunk_null_cache_and_freshness","missing_cache_and_fresh_source",()->{Fixture f=new Fixture(x->x.world.chunks.missing=true);Object m=construct(nested(candidate,"ReadMetrics"));Object s=source(f,m);f.clearTrace();Object a=cell(s,0,64,0);Object b=cell(s,0,64,0);eq(a,b,"same missing Cell");eq(1L,count(f.trace(),"chunks.getChunk:"),"one missing chunk fetch per source");eq(2L,field(m,"chunkRequests"),"two requests");eq(1L,field(m,"chunkCacheHits"),"null cache hit");f.world.chunks.missing=false;eq(a,cell(s,0,64,0),"old source retains missing result within source lifetime");f.clearTrace();Object fresh=source(f,null);Object loaded=cell(fresh,0,64,0);eq("LOADED",call(loaded.getClass(),loaded,"availability").toString(),"new source sees loaded chunk");eq(1L,count(f.trace(),"chunks.getChunk:"),"new source fetches once");});
  for(String guard:List.of("wrong_thread","no_player","no_level"))wrapper("actual_factory_thread_and_world_guards","guards_"+guard,()->{
   Fixture f=new Fixture(x->{if(guard.equals("wrong_thread"))x.mc.sameThread=false;if(guard.equals("no_player"))x.mc.player=null;if(guard.equals("no_level"))x.mc.level=null;});
   expectException("java.lang.IllegalStateException",guard.equals("wrong_thread")?"minecraft_thread_required":"not_in_world",()->source(f,null));
   if(guard.equals("wrong_thread"))expectException("java.lang.IllegalStateException","minecraft_thread_required",()->call(candidate,null,"flatStepResult",f.mc,0d,0d));
   else {Object result=call(candidate,null,"flatStepResult",f.mc,0d,0d);eq("not_in_world",call(result.getClass(),result,"reason"),"flatStep no world reason");}
   for(Class<?> reader:List.of(legacy,candidate))expectException(guard.equals("wrong_thread")?"java.lang.IllegalStateException":"io.github.campione01.mineclientbridge.TerrainScan$Failure",guard.equals("wrong_thread")?"Terrain reads require the Minecraft thread":"not_in_world",()->page(reader,"radius=0&vertical=0&limit=1"));
  });
  for(String variant:List.of("loaded","unloaded","out_of_world","metadata_throw","collision_throw","null_property_name","null_property_value","null_fluid_state"))wrapper("actual_page_unknown_serialization","page_"+variant,()->{
   Consumer<Fixture> setup=f->{if(variant.equals("unloaded"))f.world.chunks.missing=true;if(variant.equals("out_of_world"))f.mc.player.y=320;if(variant.equals("metadata_throw"))Trace.failures.add("state.isAir");if(variant.equals("collision_throw"))Trace.failures.add("state.getCollisionShape:0,64,0");if(variant.equals("null_property_name"))addProp(f,null,"v");if(variant.equals("null_property_value"))addProp(f,"p",null);if(variant.equals("null_fluid_state"))f.state.fluid=null;};
   JsonObject old=null;for(Class<?> reader:List.of(legacy,candidate)){new Fixture(setup);JsonObject value=page(reader,"radius=0&vertical=0&limit=1");JsonObject c=value.getAsJsonArray("cells").get(0).getAsJsonObject();String expected=variant.equals("unloaded")?"unloaded":variant.equals("out_of_world")?"out_of_world":variant.equals("loaded")||variant.equals("collision_throw")?"loaded":"read_failed";eq(expected,c.get("status").getAsString(),"page exact failure status");eq(expected.equals("loaded"),c.get("known").getAsBoolean(),"page known");eq(expected.equals("loaded")?0:1,value.get("unknown_cells").getAsInt(),"page unknown count");eq(1,value.get("returned").getAsInt(),"one returned");eq(true,value.get("complete").getAsBoolean(),"complete");yes(value.get("next_cursor").isJsonNull(),"explicit null cursor");if(!expected.equals("loaded"))for(String key:List.of("id","air","fluid","collision_known"))yes(!c.has(key),"unknown omits fabricated "+key);if(variant.equals("collision_throw")){eq(false,c.get("collision_known").getAsBoolean(),"collision failure stays loaded");eq("block_shape_failed",c.get("collision_unknown_reason").getAsString(),"collision reason");}if(old==null)old=normalizedPage(value);else eq(old,normalizedPage(value),"full old/new page except run-specific ids/time");}
  });
  for(String variant:List.of("clear","metadata_throw","collision_unknown","unloaded","null_property_name","null_property_value","null_fluid_state"))wrapper("actual_flat_step_failure_translation","flat_"+variant,()->{
   Fixture f=new Fixture(x->{x.world.chunks.chunk.lookup=p->p.y()==63?x.state:x.air;if(variant.equals("metadata_throw"))Trace.failures.add("state.isAir");if(variant.equals("collision_unknown"))x.state.shape=null;if(variant.equals("unloaded"))x.world.chunks.missing=true;if(variant.equals("null_property_name"))addProp(x,null,"v");if(variant.equals("null_property_value"))addProp(x,"p",null);if(variant.equals("null_fluid_state"))x.state.fluid=null;});
   Object result=call(candidate,null,"flatStepResult",f.mc,0d,0d);String reason=variant.equals("clear")?"clear":variant.equals("collision_unknown")?"collision_unknown":variant.equals("unloaded")?"unloaded":"cell_read_failed";eq(reason,call(result.getClass(),result,"reason"),"actual corridor failure translation");eq(reason.equals("clear"),call(result.getClass(),result,"clear"),"actual clear status");Object ref=call(result.getClass(),result,"cell");if(reason.equals("clear"))eq(null,ref,"clear no denied cell");else {eq(0,call(ref.getClass(),ref,"x"),"support x");eq(63,call(ref.getClass(),ref,"y"),"support y");eq(0,call(ref.getClass(),ref,"z"),"support z");eq("support",call(ref.getClass(),ref,"layer"),"support layer");eq(reason.equals("collision_unknown")?"minecraft:stone":null,call(ref.getClass(),ref,"id"),"denied available id");}
  });
  wrapper("actual_page_replay_and_pose","page_replay_pose_ticks",()->{
   List<List<JsonObject>> sequences=new ArrayList<>();for(Class<?> reader:List.of(legacy,candidate)){
    Fixture f=new Fixture(x->{});JsonObject a=page(reader,"radius=1&vertical=0&limit=1");String generation=a.get("generation").getAsString(),worldId=a.get("world_generation").getAsString(),cursor=a.get("next_cursor").getAsString();eq(generation+":1",cursor,"cursor encodes next offset");
    f.mc.player.x=20.5;f.mc.player.z=30.5;f.world.time=110;JsonObject b=page(reader,"cursor="+cursor);eq(a.get("origin"),b.get("origin"),"original anchor despite movement");eq(generation,b.get("generation").getAsString(),"scan generation retained");eq(worldId,b.get("world_generation").getAsString(),"world generation retained");eq(110L,b.get("game_time").getAsLong(),"new page sampled tick");eq(1,b.get("offset").getAsInt(),"continuation offset");JsonObject bc=b.getAsJsonArray("cells").get(0).getAsJsonObject();eq(0,bc.get("x").getAsInt(),"x then z ordering");eq(-1,bc.get("z").getAsInt(),"z unchanged second cell");
    f.mc.player.x=40.5;f.world.time=120;f.clearTrace();JsonObject replay=page(reader,"cursor="+cursor);eq(0,f.trace().size(),"replay no world/block callback reads");eq(110L,replay.get("game_time").getAsLong(),"replay retains sampled tick");eq(120L,replay.get("response_game_time").getAsLong(),"replay fresh response tick");JsonObject rb=normalizedPage(b),rr=normalizedPage(replay);rb.remove("response_game_time");rr.remove("response_game_time");eq(rb,rr,"replay otherwise identical");eq(b.get("read_elapsed_micros"),replay.get("read_elapsed_micros"),"replay retained elapsed evidence");sequences.add(List.of(normalizedPage(a),normalizedPage(b),normalizedPage(replay)));
   }eq(sequences.get(0),sequences.get(1),"old/new page sequence semantics");
  });
 }
 public static void main(String[] args)throws Exception{
  legacy=Class.forName("io.github.campione01.mineclientbridge.LegacyTerrainReader");candidate=Class.forName("io.github.campione01.mineclientbridge.TerrainReader");queryType=Class.forName("io.github.campione01.mineclientbridge.TerrainQuery");
  rawCases();wrapperCases();JsonObject report=new JsonObject();report.addProperty("status",failures.isEmpty()?"semantic_checks_passed":"failed");report.addProperty("four_path_adapter_scenarios",rawCases);report.addProperty("adapter_path_executions",rawCases*4);report.addProperty("wrapper_or_metrics_scenarios",wrapperCases);report.addProperty("assertions",assertions);report.add("covered_groups",GSON.toJsonTree(groups));report.add("strict_exception_message_differences",GSON.toJsonTree(differences));report.add("failures",GSON.toJsonTree(failures));report.add("observations",GSON.toJsonTree(results));Files.writeString(Path.of(args[0]),GSON.toJson(report));System.out.println("Finite adapter: "+rawCases+" four-path scenarios, "+wrapperCases+" wrapper/metrics scenarios, "+assertions+" assertions, "+failures.size()+" semantic failures, "+differences.size()+" raw exception message differences");if(!failures.isEmpty())System.exit(1);
 }
}
