package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.*;
import java.util.function.LongSupplier;

/** Pure bounded scan state machine. A source is valid for one client tick only. */
final class LoadedScan {
    static final int BLOCKS_PER_TICK = 32_768;
    static final long BUDGET_NANOS = 2_000_000;
    static final int SURFACE_STEP = 4, WATER_RADIUS = 48;
    record Sample(String ore, boolean surface, boolean water) {
        static final Sample AIR = new Sample(null, false, false);
    }
    interface Source {
        boolean loaded(int chunkX, int chunkZ);
        boolean emptySection(int x, int y, int z);
        Sample block(int x, int y, int z);
        String biome(int x, int y, int z);
    }
    record Chunk(int x, int z) { }
    record Surface(int x, int y, int z, boolean water, String biome, long at) { }
    record ClusterKey(String id, int x, int y, int z) { }
    static final class Cluster {
        final ClusterKey key;
        long count, at;
        int minX=Integer.MAX_VALUE,minY=Integer.MAX_VALUE,minZ=Integer.MAX_VALUE;
        int maxX=Integer.MIN_VALUE,maxY=Integer.MIN_VALUE,maxZ=Integer.MIN_VALUE;
        final List<int[]> samples = new ArrayList<>();
        Cluster(ClusterKey key) { this.key=key; }
        void add(int x,int y,int z,long now) { count++;at=now; minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);minZ=Math.min(minZ,z);maxZ=Math.max(maxZ,z);if(samples.size()<4)samples.add(new int[]{x,y,z}); }
    }
    static final class Region {
        final int chunkX,chunkZ;
        long count,at;boolean complete;int minY=Integer.MAX_VALUE,maxY=Integer.MIN_VALUE;
        final Map<String,Long> counts=new TreeMap<>();
        final List<JsonObject> samples=new ArrayList<>();
        Surface ground,water;double waterDistance;int relief,neighbors;
        Region(int x,int z){chunkX=x;chunkZ=z;}
    }
    record Site(Surface ground, Surface water, double waterDistance, int relief, int neighbors, double distance, double score) { }
    final LoadedScanRequest request;
    final LoadedScanRequest.Bounds bounds;
    final String dimension, generation;
    final int originX,originY,originZ;
    final long started;
    final List<Chunk> chunks = new ArrayList<>();
    final Map<String,Long> oreCounts = new TreeMap<>();
    final LinkedHashMap<ClusterKey,Cluster> clusters = new LinkedHashMap<>();
    final Map<Long,Surface> surfaces = new HashMap<>();
    final List<JsonObject> unknown = new ArrayList<>();
    final List<Site> sites = new ArrayList<>();
    private Iterator<Surface> siteIterator;
    private Iterator<Region> regionIterator;
    final Map<Long,Region> regions=new LinkedHashMap<>();
    long biomeSamplesTested,biomeSamplesMatched;
    private int chunkIndex,x,z,y;
    private boolean columnHasSurface;
    long scanned, unknownBlocks, skippedAir, processingNanos, lastAt, finished;
    long oreMatches, clusterOverflow, candidateCount;
    int unknownChunks, completedChunks, ticks;
    String status="running", reason, phase="blocks";
    private final LongSupplier nanoTime;

    LoadedScan(LoadedScanRequest request, LoadedScanRequest.Bounds resolved, String dimension, String generation,
               int ox,int oy,int oz,long now,LongSupplier nanoTime) {
        this.request=request;bounds=resolved;this.dimension=dimension;this.generation=generation;
        originX=ox;originY=oy;originZ=oz;started=lastAt=now;this.nanoTime=nanoTime;
        LoadedScanRequest.validateXZ(bounds);
        if(bounds.minY()==null||bounds.maxY()==null||bounds.minY()>bounds.maxY())throw LoadedScanRequest.bad("invalid_scan_height");
        for(int cx=bounds.minX()>>4;cx<=bounds.maxX()>>4;cx++) for(int cz=bounds.minZ()>>4;cz<=bounds.maxZ()>>4;cz++) chunks.add(new Chunk(cx,cz));
        chunks.sort(Comparator.comparingLong(c->distanceSquared((c.x<<4)+8,(c.z<<4)+8,ox,oz)));
        beginChunk();
    }
    private static long distanceSquared(int x,int z,int ox,int oz) {long dx=(long)x-ox,dz=(long)z-oz;return dx*dx+dz*dz;}
    private void beginChunk() { if(chunkIndex<chunks.size()){Chunk c=chunks.get(chunkIndex);x=Math.max(bounds.minX(),c.x<<4);z=Math.max(bounds.minZ(),c.z<<4);y=bounds.maxY();columnHasSurface=false;} }
    private int endX(){return Math.min(bounds.maxX(),(chunks.get(chunkIndex).x<<4)+15);}
    private int endZ(){return Math.min(bounds.maxZ(),(chunks.get(chunkIndex).z<<4)+15);}
    void tick(Source source,long now) {
        if(!status.equals("running"))return;
        long start=nanoTime.getAsLong();int work=0;ticks++;
        try {
            while(work<BLOCKS_PER_TICK && nanoTime.getAsLong()-start<BUDGET_NANOS && status.equals("running")) {
                if(phase.equals("regions")){if(!regionIterator.hasNext()){finish("succeeded",null,now);break;}evaluateRegion(regionIterator.next());work+=128;continue;}
                if(phase.equals("sites")){ if(!siteIterator.hasNext()){phase="regions";regionIterator=regions.values().iterator();continue;} evaluate(siteIterator.next());work+=64;continue; }
                if(chunkIndex==chunks.size()) { if(request.surfaceResults()){phase="sites";siteIterator=surfaces.values().iterator();continue;} phase="regions";regionIterator=regions.values().iterator();continue; }
                Chunk c=chunks.get(chunkIndex);
                lastAt=now;
                if(!source.loaded(c.x,c.z)) {
                    long height=(long)bounds.maxY()-bounds.minY()+1;
                    long remaining=((long)endX()-x)*(endZ()-Math.max(bounds.minZ(),c.z<<4)+1)*height
                            +((long)endZ()-z)*height+(y-bounds.minY()+1L);
                    unknownBlocks+=remaining;unknownChunks++;
                    if(unknown.size()<64){JsonObject u=new JsonObject();u.addProperty("chunk_x",c.x);u.addProperty("chunk_z",c.z);u.addProperty("remaining_blocks",remaining);u.addProperty("reason","not_loaded_at_read");unknown.add(u);}
                    chunkIndex++;beginChunk();work++;continue;
                }
                if(!request.biomes() && (y&15)==15 && y-15>=bounds.minY() && source.emptySection(x,y,z)) {scanned+=16;skippedAir+=16;work++;advance(16);continue;}
                Sample b=request.biomes()&&!request.sites()?Sample.AIR:source.block(x,y,z);scanned++;work++;
                if(request.ores()&&b.ore!=null&&(request.biomeIds().isEmpty()||request.biomeIds().contains(source.biome(x,y,z))))recordOre(b.ore,x,y,z,now);
                if(request.biomes()&&((x&3)==0||x==bounds.minX())&&((y&3)==0||y==bounds.minY())&&((z&3)==0||z==bounds.minZ())){biomeSamplesTested++;String biome=source.biome(x,y,z);if(request.biomeIds().contains(biome)){biomeSamplesMatched++;recordOre(biome,x,y,z,now);}}
                if(request.sites()&&!columnHasSurface&&(x&3)==0&&(z&3)==0&&b.surface) {
                    surfaces.put(key(x,z),new Surface(x,y,z,b.water,source.biome(x,Math.min(y+1,bounds.maxY()),z),now));columnHasSurface=true;
                }
                advance(1);
            }
        } finally { processingNanos+=Math.max(0,nanoTime.getAsLong()-start); }
    }
    private void advance(int count) {y-=count;if(y>=bounds.minY())return;y=bounds.maxY();columnHasSurface=false;z++;if(z<=endZ())return;z=Math.max(bounds.minZ(),chunks.get(chunkIndex).z<<4);x++;if(x<=endX())return;Region r=regions.get(key(chunks.get(chunkIndex).x,chunks.get(chunkIndex).z));if(r!=null)r.complete=true;completedChunks++;chunkIndex++;beginChunk();}
    private void recordOre(String id,int x,int y,int z,long now){
        oreMatches++;oreCounts.merge(id,1L,Long::sum);
        Region region=regions.computeIfAbsent(key(x>>4,z>>4),k->new Region(x>>4,z>>4));
        region.count++;region.at=now;region.minY=Math.min(region.minY,y);region.maxY=Math.max(region.maxY,y);region.counts.merge(id,1L,Long::sum);
        if(region.samples.size()<4){JsonObject p=point(x,y,z);p.addProperty("id",id);region.samples.add(p);}
        ClusterKey key=new ClusterKey(id,x>>4,y>>4,z>>4);Cluster c=clusters.get(key);
        if(c==null){if(clusters.size()>=request.maxResults()){clusterOverflow++;return;}c=new Cluster(key);clusters.put(key,c);}c.add(x,y,z,now);
    }
    private static long key(int x,int z){return ((long)x<<32)|(z&0xffffffffL);}
    private void evaluate(Surface ground){
        if(request.explicitBlockFilter()&&!regions.containsKey(key(ground.x>>4,ground.z>>4)))return;
        if(ground.water||(!request.biomeIds().isEmpty()&&!request.biomeIds().contains(ground.biome)))return;
        Surface nearest=null;double best=Double.POSITIVE_INFINITY;
        for(int dx=-(request.waterRadius()/4)*4;dx<=request.waterRadius();dx+=SURFACE_STEP)for(int dz=-(request.waterRadius()/4)*4;dz<=request.waterRadius();dz+=SURFACE_STEP){
            int d=dx*dx+dz*dz;if(d>request.waterRadius()*request.waterRadius()||d>=best)continue;
            Surface s=surfaces.get(key(ground.x+dx,ground.z+dz));if(s!=null&&s.water){nearest=s;best=d;}
        }
        if(nearest==null&&request.requireWater())return;
        if(nearest==null)best=0;
        int min=ground.y,max=ground.y,neighbors=0;
        for(int dx=-4;dx<=4;dx+=4)for(int dz=-4;dz<=4;dz+=4){if(dx==0&&dz==0)continue;Surface s=surfaces.get(key(ground.x+dx,ground.z+dz));if(s!=null&&!s.water){min=Math.min(min,s.y);max=Math.max(max,s.y);neighbors++;}}
        double distance=Math.sqrt(distanceSquared(ground.x,ground.z,originX,originZ));
        Site site=new Site(ground,nearest,Math.sqrt(best),max-min,neighbors,distance,distance+Math.sqrt(best)*2+(max-min)*4);
        candidateCount++;
        // One best observed sample per 16x16 tile; do not flood a result with adjacent grid points.
        for(int i=0;i<sites.size();i++){Site old=sites.get(i);if((old.ground.x>>4)==(ground.x>>4)&&(old.ground.z>>4)==(ground.z>>4)){if(site.score<old.score)sites.set(i,site);return;}}
        if(sites.size()<request.maxResults()){sites.add(site);return;}
        int worst=0;for(int i=1;i<sites.size();i++)if(sites.get(i).score>sites.get(worst).score)worst=i;
        if(site.score<sites.get(worst).score)sites.set(worst,site);
    }
    private void evaluateRegion(Region region){
        int cx=(region.chunkX<<4)+8,cz=(region.chunkZ<<4)+8;
        long best=Long.MAX_VALUE;
        for(int dx=-8;dx<8;dx+=4)for(int dz=-8;dz<8;dz+=4){Surface g=surfaces.get(key(cx+dx,cz+dz));if(g!=null&&!g.water&&dx*dx+dz*dz<best){best=dx*dx+dz*dz;region.ground=g;}}
        if(region.ground==null)return;
        int low=region.ground.y,high=low;
        for(int dx=-4;dx<=4;dx+=4)for(int dz=-4;dz<=4;dz+=4){if(dx==0&&dz==0)continue;Surface neighbor=surfaces.get(key(region.ground.x+dx,region.ground.z+dz));if(neighbor!=null&&!neighbor.water){low=Math.min(low,neighbor.y);high=Math.max(high,neighbor.y);region.neighbors++;}}
        region.relief=high-low;
        best=Long.MAX_VALUE;
        int radius=request.waterRadius()/4*4;
        for(int dx=-radius;dx<=radius;dx+=4)for(int dz=-radius;dz<=radius;dz+=4){long distance=(long)dx*dx+(long)dz*dz;if(distance>request.waterRadius()*request.waterRadius()||distance>=best)continue;Surface water=surfaces.get(key(region.ground.x+dx,region.ground.z+dz));if(water!=null&&water.water){best=distance;region.water=water;region.waterDistance=Math.sqrt(distance);}}
    }
    private long regionVolume(Region r){return (long)(Math.min(bounds.maxX(),(r.chunkX<<4)+15)-Math.max(bounds.minX(),r.chunkX<<4)+1)*(Math.min(bounds.maxZ(),(r.chunkZ<<4)+15)-Math.max(bounds.minZ(),r.chunkZ<<4)+1)*(bounds.maxY()-bounds.minY()+1L);}
    private JsonArray regionResults(){
        Comparator<Region> byDistance=Comparator.comparingLong(r->distanceSquared((r.chunkX<<4)+8,(r.chunkZ<<4)+8,originX,originZ));
        Comparator<Region> comparator=request.sort().equals("distance")?byDistance:
                request.sort().equals("density")?Comparator.<Region>comparingDouble(r->(double)r.count/regionVolume(r)).reversed().thenComparing(byDistance):
                Comparator.<Region>comparingLong(r->r.count).reversed().thenComparing(byDistance);
        JsonArray output=new JsonArray();
        regions.values().stream().filter(r->!request.requireWater()||r.water!=null).sorted(comparator).limit(request.maxResults()).forEach(r->{
            JsonObject v=new JsonObject();v.addProperty("chunk_x",r.chunkX);v.addProperty("chunk_z",r.chunkZ);v.addProperty("match_count",r.count);v.addProperty("min_matched_y",r.minY);v.addProperty("max_matched_y",r.maxY);v.addProperty("observed_at_ms",r.at);
            v.addProperty("distance_from_scan_origin",Math.sqrt(distanceSquared((r.chunkX<<4)+8,(r.chunkZ<<4)+8,originX,originZ)));
            long volume=regionVolume(r);
            v.addProperty("region_volume",volume);v.addProperty("matches_per_region_block",(double)r.count/volume);v.addProperty("counts_complete",r.complete);v.addProperty("density_unit",request.biomes()?"matched_quart_origins_per_requested_block_volume":"matching_blocks_per_requested_block_volume");
            JsonObject counts=new JsonObject();r.counts.forEach(counts::addProperty);v.add("counts_by_id",counts);JsonArray samples=new JsonArray();r.samples.forEach(samples::add);v.add("sample_positions",samples);
            if(r.ground!=null){v.add("surface",point(r.ground.x,r.ground.y,r.ground.z));v.addProperty("surface_biome_id",r.ground.biome);v.addProperty("local_height_range",r.relief);v.addProperty("local_neighbor_samples",r.neighbors);v.addProperty("local_slope_rise_per_block",r.relief/8.0);v.addProperty("terrain_samples_complete",r.neighbors==8);}
            if(r.water!=null){v.add("nearby_surface_water",point(r.water.x,r.water.y,r.water.z));v.addProperty("water_horizontal_distance",r.waterDistance);v.addProperty("water_vertical_difference",r.ground.y-r.water.y);}
            v.addProperty("ownership","unknown");v.addProperty("candidate_only",true);output.add(v);
        });return output;
    }
    void finish(String state,String why,long now){status=state;reason=why;finished=now;}
    JsonObject snapshot(long now){
        JsonObject o=new JsonObject();o.addProperty("ok",true);o.addProperty("scan_schema_version",1);o.addProperty("scan_id",request.id());o.addProperty("status",status);o.addProperty("phase",phase);if(reason!=null)o.addProperty("reason",reason);
        o.addProperty("mode",request.mode());o.addProperty("dimension",dimension);o.addProperty("world_generation",generation);
        o.addProperty("read_only",true);o.addProperty("loaded_chunks_only",true);o.addProperty("consistency","live_observations_not_atomic_snapshot");
        o.addProperty("started_at_ms",started);o.addProperty("observed_at_ms",lastAt);if(finished>0)o.addProperty("finished_at_ms",finished);o.addProperty("elapsed_ms",(finished>0?finished:now)-started);o.addProperty("processing_micros",processingNanos/1000);o.addProperty("ticks",ticks);
        JsonObject coverage=new JsonObject();JsonObject b=new JsonObject();b.addProperty("min_x",bounds.minX());b.addProperty("max_x",bounds.maxX());b.addProperty("min_z",bounds.minZ());b.addProperty("max_z",bounds.maxZ());b.addProperty("min_y",bounds.minY());b.addProperty("max_y",bounds.maxY());coverage.add("bounds",b);
        coverage.addProperty("total_blocks",((long)bounds.maxX()-bounds.minX()+1)*(bounds.maxZ()-bounds.minZ()+1)*(bounds.maxY()-bounds.minY()+1));coverage.addProperty("scanned_blocks",scanned);coverage.addProperty("known_air_blocks_skipped",skippedAir);coverage.addProperty("chunks_total",chunks.size());coverage.addProperty("chunks_completed",completedChunks);coverage.addProperty("unknown_chunks",unknownChunks);coverage.addProperty("unknown_remaining_blocks",unknownBlocks);
        coverage.addProperty("scan_complete",status.equals("succeeded"));coverage.addProperty("outside_bounds","not_observed");coverage.addProperty("surface_sample_step",SURFACE_STEP);coverage.addProperty("surface_columns",surfaces.size());JsonArray u=new JsonArray();unknown.forEach(u::add);coverage.add("unknown_chunk_examples",u);coverage.addProperty("unknown_examples_truncated",unknownChunks>unknown.size());o.add("coverage",coverage);
        JsonObject results=new JsonObject();JsonObject counts=new JsonObject();oreCounts.forEach(counts::addProperty);results.add("ore_counts",counts);results.addProperty("ore_matches",oreMatches);results.addProperty("ore_cluster_definition","same_block_id_in_16x16x16_bin_not_connected_vein");results.addProperty("ore_cluster_order","first_observed_near_origin_chunks_top_down");results.addProperty("ore_matches_without_cluster_detail",clusterOverflow);
        JsonArray ores=new JsonArray();for(Cluster c:clusters.values()){JsonObject v=new JsonObject();v.addProperty("id",c.key.id);v.addProperty("count",c.count);v.addProperty("observed_at_ms",c.at);JsonArray box=new JsonArray();for(int n:new int[]{c.minX,c.minY,c.minZ,c.maxX,c.maxY,c.maxZ})box.add(n);v.add("bounds_xyz",box);JsonArray samples=new JsonArray();for(int[] p:c.samples)samples.add(point(p[0],p[1],p[2]));v.add("sample_positions",samples);ores.add(v);}results.add("ore_clusters",ores);results.addProperty("ore_clusters_truncated",clusterOverflow>0);
        JsonArray candidates=new JsonArray();sites.stream().sorted(Comparator.comparingDouble(Site::score)).forEach(site->{JsonObject s=point(site.ground.x,site.ground.y,site.ground.z);s.addProperty("biome_id",site.ground.biome);s.addProperty("biome_source","loaded_chunk_quart_biome_at_surface");s.addProperty("observed_at_ms",site.ground.at);if(site.water!=null){s.add("water",point(site.water.x,site.water.y,site.water.z));s.addProperty("water_observed_at_ms",site.water.at);s.addProperty("water_horizontal_distance",site.waterDistance);s.addProperty("water_vertical_difference",site.ground.y-site.water.y);}s.addProperty("distance_from_scan_origin",site.distance);s.addProperty("local_height_range",site.relief);s.addProperty("local_neighbor_samples",site.neighbors);s.addProperty("local_slope_rise_per_block",site.relief/8.0);s.addProperty("terrain_samples_complete",site.neighbors==8);s.addProperty("candidate_only",true);candidates.add(s);});results.add("cherry_sites",candidates);results.addProperty("matching_surface_samples",candidateCount);results.addProperty("water_search_radius",request.waterRadius());results.addProperty("ownership","unknown");results.addProperty("safety","not_assessed");results.addProperty("water_source","top_terrain_surface_water_vegetation_ignored_not_cave_water");results.add("regions",regionResults());results.addProperty("region_sort",request.sort());results.addProperty("region_count",regions.size());results.addProperty("match_unit",request.biomes()?"sampled_quart_biome_at_representative_block":"block");results.addProperty("biome_samples_tested",biomeSamplesTested);results.addProperty("biome_samples_matched",biomeSamplesMatched);
        results.add("block_counts",counts.deepCopy());results.add("block_clusters",ores.deepCopy());results.add("surface_sites",candidates.deepCopy());
        // Alias arrays would duplicate a large payload. Use generic keys for generic modes.
        if(!request.mode().equals("ores")&&!request.mode().equals("both")){results.remove("ore_counts");results.remove("ore_clusters");}
        if(!request.mode().equals("cherry_sites")){results.remove("cherry_sites");}
        else results.remove("surface_sites");
        if(request.mode().equals("ores")||request.mode().equals("both")){results.remove("block_counts");results.remove("block_clusters");}
        if(request.biomes()){results.add("biome_counts",results.remove("block_counts"));results.add("biome_clusters",results.remove("block_clusters"));}
        o.add("results",results);compact(o,results);return o;
    }
    /** Keep output comfortably inside the existing 256 KiB authenticated transport ceiling. */
    private static void compact(JsonObject response,JsonObject results){
        int bytes=response.toString().length(); // All IDs are restricted ASCII, as are schema and status strings.
        while(bytes>192*1024){
            double fraction=170.0*1024/bytes;boolean removed=false;
            for(String name:List.of("regions","ore_clusters","block_clusters","biome_clusters","cherry_sites","surface_sites")){
                if(!results.has(name))continue;
                JsonArray array=results.getAsJsonArray(name);int keep=(int)(array.size()*fraction);
                while(array.size()>keep){array.remove(array.size()-1);removed=true;}
            }
            results.addProperty("response_details_truncated",true);
            if(!removed)break;
            bytes=response.toString().length();
        }
    }
    private static JsonObject point(int x,int y,int z){JsonObject o=new JsonObject();o.addProperty("x",x);o.addProperty("y",y);o.addProperty("z",z);return o;}
}
