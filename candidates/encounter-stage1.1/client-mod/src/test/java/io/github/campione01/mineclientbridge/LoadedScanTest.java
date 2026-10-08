package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class LoadedScanTest {
    private LoadedScanRequest request(String json){return LoadedScanRequest.parse(JsonParser.parseString(json).getAsJsonObject());}
    private LoadedScan scan(String query,int minX,int maxX,int minZ,int maxZ,int minY,int maxY){return new LoadedScan(request(query),new LoadedScanRequest.Bounds(minX,maxX,minZ,maxZ,minY,maxY),"minecraft:overworld","world-a",0,64,0,1000,()->0L);}
    private static class Source implements LoadedScan.Source {
        Set<String> missing=new HashSet<>(); Map<String,LoadedScan.Sample> blocks=new HashMap<>();Map<String,String> biomes=new HashMap<>();int reads;
        String key(int x,int y,int z){return x+","+y+","+z;}
        public boolean loaded(int x,int z){return !missing.contains(x+","+z);}
        public boolean emptySection(int x,int y,int z){return false;}
        public LoadedScan.Sample block(int x,int y,int z){reads++;return blocks.getOrDefault(key(x,y,z),LoadedScan.Sample.AIR);}
        public String biome(int x,int y,int z){return biomes.getOrDefault(x+","+z,"minecraft:plains");}
        void block(int x,int y,int z,String id,boolean solid,boolean water){blocks.put(key(x,y,z),new LoadedScan.Sample(id,solid,water));}
        void ground(int x,int z,int y){block(x,y,z,null,true,false);}
        void water(int x,int z,int y){block(x,y,z,null,true,true);}
    }
    private void complete(LoadedScan scan,Source source){for(int n=0;n<1000&&scan.status.equals("running");n++)scan.tick(source,1000+n);assertEquals("succeeded",scan.status);}
    @Test void strictRequestAndPresetValidation(){
        var r=request("{\"id\":\"one\",\"mode\":\"blocks\",\"block_ids\":[\"minecraft:cherry_log\"],\"require_water\":true,\"sort\":\"distance\"}");
        assertEquals(Set.of("minecraft:cherry_log"),r.oreIds());assertTrue(r.biomeIds().isEmpty());assertTrue(r.sites());assertTrue(r.requireWater());
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"max_results\":257}"));
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"block_ids\":[\"minecraft:air\"],\"ore_ids\":[\"minecraft:air\"]}"));
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"require_water\":1}"));
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"wat\":1}"));
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"mode\":\"biomes\"}"));
    }
    @Test void rejectsOversizedOrReversedBounds(){
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"bounds\":{\"min_x\":0,\"max_x\":3000,\"min_z\":0,\"max_z\":1}}"));
        assertThrows(ClientActionRequest.Rejected.class,()->request("{\"id\":\"x\",\"bounds\":{\"min_x\":0,\"max_x\":-1,\"min_z\":0,\"max_z\":1}}"));
    }
    @Test void scansFullRequestedVerticalAndPreservesOreCoordinates(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"ores\"}",-20,20,0,0,-64,319);var src=new Source();src.block(-20,-64,0,"minecraft:iron_ore",true,false);src.block(20,300,0,"minecraft:coal_ore",true,false);complete(scan,src);
        assertEquals(41*384,scan.scanned);assertEquals(1L,scan.oreCounts.get("minecraft:iron_ore"));assertEquals(1L,scan.oreCounts.get("minecraft:coal_ore"));assertEquals(2,scan.regions.size());
    }
    @Test void missingAndUnloadedMidScanStayUnknown(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"ores\"}",0,15,0,15,-64,319);var src=new Source();scan.tick(src,1000);assertEquals(32768,scan.scanned);assertEquals("running",scan.status);src.missing.add("0,0");complete(scan,src);
        assertEquals(65536,scan.unknownBlocks);assertEquals(1,scan.unknownChunks);assertEquals(0,scan.completedChunks);assertEquals(98304,scan.scanned+scan.unknownBlocks);
    }
    @Test void timeBudgetStopsWithoutExtraReads(){
        AtomicLong clock=new AtomicLong();var req=request("{\"id\":\"x\",\"mode\":\"ores\"}");
        var scan=new LoadedScan(req,new LoadedScanRequest.Bounds(0,15,0,15,0,319),"dim","gen",0,0,0,1000,()->clock.getAndAdd(500_000));var src=new Source();scan.tick(src,1001);assertTrue(src.reads<=3);assertEquals("running",scan.status);
    }
    @Test void emptySectionsAreKnownAirNotUnknown(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"ores\"}",0,0,0,0,-64,319);var src=new Source(){public boolean emptySection(int x,int y,int z){return true;}};complete(scan,src);assertEquals(384,scan.skippedAir);assertEquals(0,src.reads);assertEquals(384,scan.scanned);
    }
    @Test void regionRankingFindsConcentratedFartherBlocksDespiteDetailLimit(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"blocks\",\"block_ids\":[\"minecraft:cherry_log\"],\"max_results\":1}",0,31,0,0,0,31);var src=new Source();src.block(0,0,0,"minecraft:cherry_log",true,false);for(int x=16;x<22;x++)src.block(x,0,0,"minecraft:cherry_log",true,false);complete(scan,src);
        JsonObject region=scan.snapshot(2000).getAsJsonObject("results").getAsJsonArray("regions").get(0).getAsJsonObject();assertEquals(1,region.get("chunk_x").getAsInt());assertEquals(6,region.get("match_count").getAsInt());assertEquals(7,scan.oreMatches);
    }
    @Test void biomeRestrictionUsesRegistryIdNotTreeAppearance(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"blocks\",\"block_ids\":[\"minecraft:cherry_log\"],\"biome_ids\":[\"minecraft:cherry_grove\"]}",0,4,0,0,0,1);var src=new Source();src.block(0,0,0,"minecraft:cherry_log",true,false);src.block(4,0,0,"minecraft:cherry_log",true,false);src.biomes.put("4,0","minecraft:cherry_grove");complete(scan,src);assertEquals(1,scan.oreMatches);
    }
    @Test void biomeModeSamplesActualQuartCellsIncludingAir(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"biomes\",\"biome_ids\":[\"minecraft:cherry_grove\"]}",0,7,0,7,0,7);var src=new Source(){public boolean emptySection(int x,int y,int z){return true;}};src.biomes.put("4,4","minecraft:cherry_grove");complete(scan,src);assertEquals(8,scan.biomeSamplesTested);assertEquals(2,scan.biomeSamplesMatched);assertEquals(0,src.reads);
    }
    @Test void topSurfaceRejectsCaveWaterAndAllowsRealSurfaceWater(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"cherry_sites\"}",0,8,0,0,0,16);var src=new Source();src.ground(0,0,10);src.biomes.put("0,0","minecraft:cherry_grove");src.ground(4,0,12);src.water(4,0,4);complete(scan,src);assertEquals(0,scan.sites.size());
        scan=scan("{\"id\":\"y\",\"mode\":\"cherry_sites\"}",0,8,0,0,0,16);src.water(8,0,10);complete(scan,src);assertEquals(1,scan.sites.size());assertEquals(8,scan.sites.getFirst().waterDistance());
    }
    @Test void plantedCherryConcentrationDoesNotRequireCherryBiome(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"blocks\",\"block_ids\":[\"minecraft:cherry_log\"],\"require_water\":true}",0,15,0,15,0,16);var src=new Source();src.ground(8,8,10);src.block(8,11,8,"minecraft:cherry_log",false,false);src.water(12,8,10);complete(scan,src);
        var regions=scan.snapshot(2000).getAsJsonObject("results").getAsJsonArray("regions");assertEquals(1,regions.size());assertEquals("minecraft:plains",regions.get(0).getAsJsonObject().get("surface_biome_id").getAsString());
    }
    @Test void cancellationStopsFurtherReads(){var scan=scan("{\"id\":\"x\"}",0,15,0,15,0,319);var src=new Source();scan.finish("cancelled","cancel_requested",1001);scan.tick(src,1002);assertEquals(0,src.reads);assertEquals("cancelled",scan.status);}
    @Test void biomeWaterCombinationReadsRealSurface(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"biomes\",\"biome_ids\":[\"minecraft:plains\"],\"require_water\":true}",0,15,0,15,0,16);var src=new Source();src.ground(8,8,10);src.water(12,8,10);complete(scan,src);
        assertTrue(src.reads>0);assertEquals(1,scan.snapshot(2000).getAsJsonObject("results").getAsJsonArray("regions").size());
    }
    @Test void surfaceSiteExplicitBlockFilterIsNotIgnored(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"surface_sites\",\"block_ids\":[\"minecraft:cherry_log\"]}",0,31,0,0,0,16);var src=new Source();src.ground(0,0,10);src.ground(20,0,10);src.block(20,11,0,"minecraft:cherry_log",false,false);complete(scan,src);
        assertEquals(1,scan.sites.size());assertEquals(20,scan.sites.getFirst().ground().x());
    }
    @Test void finishingDoesNotRefreshObservationTime(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"ores\"}",0,0,0,0,0,0);var src=new Source();complete(scan,src);long observed=scan.lastAt;scan.finish("cancelled","reason",9000);assertEquals(observed,scan.lastAt);assertEquals(9000,scan.finished);
    }
    @Test void unfinishedUnloadedRegionIsNotMarkedComplete(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"ores\"}",0,15,0,15,-64,319);var src=new Source();src.block(0,319,0,"minecraft:iron_ore",true,false);scan.tick(src,1001);src.missing.add("0,0");complete(scan,src);assertFalse(scan.regions.values().iterator().next().complete);
    }
    @Test void compactOutputHonorsTransportCeilingWithoutDroppingTotals(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"blocks\",\"max_results\":256}",0,15,0,15,0,319);
        for(int x=0;x<256;x++){var r=new LoadedScan.Region(x,0);r.count=123;r.at=1000;r.minY=0;r.maxY=300;for(int i=0;i<32;i++)r.counts.put("a".repeat(40)+":"+"b".repeat(90)+i,123L);scan.regions.put((long)x,r);}
        scan.oreCounts.put("minecraft:iron_ore",99999L);var json=scan.snapshot(2000);assertTrue(json.toString().length()<=192*1024);assertTrue(json.getAsJsonObject("results").get("response_details_truncated").getAsBoolean());assertEquals(99999L,json.getAsJsonObject("results").getAsJsonObject("block_counts").get("minecraft:iron_ore").getAsLong());
    }
    @Test void partialQuartBoundsStillSampleTheirBiome(){
        var scan=scan("{\"id\":\"x\",\"mode\":\"biomes\",\"biome_ids\":[\"minecraft:plains\"]}",1,1,1,1,1,1);complete(scan,new Source());assertEquals(1,scan.biomeSamplesTested);assertEquals(1,scan.biomeSamplesMatched);
    }
    @Test void sourceContractNeverLoadsChunksOrUsesServerOrInputs()throws Exception{
        var root=Path.of(System.getProperty("mineclientBridge.projectDir"));var source=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/LoadedWorldScanner.java"));
        assertTrue(source.contains("ChunkStatus.FULL,false"));assertTrue(source.contains("getNoiseBiome"));assertTrue(source.contains("new Source(activeLevel,active.request)"));assertTrue(source.contains("site_scan_requires_world_top"));
        for(String banned:List.of("getServer(","sendCommand(","setBlock(","getSeed(","releaseAllInputs(","ClientActions.start("))assertFalse(source.contains(banned));
        String bridge=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));assertTrue(bridge.contains("requireControlAccess(exchange, \"/control/scan\", \"POST\")"));
    }
}
