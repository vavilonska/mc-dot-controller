package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/** Closed survival-mining cell vocabulary. Pure validation, no world or action authority. */
final class ScopedMiningCellPolicy {
    static final Set<String> LEGACY=ids("stone","cobblestone","dirt","andesite","granite","diorite",
        "smooth_stone","stone_bricks","bricks","oak_planks","spruce_planks","birch_planks");
    static final Set<String> LOGS=ids("oak_log","spruce_log","birch_log","jungle_log","acacia_log","dark_oak_log","mangrove_log");
    static final Set<String> ORES=ids("iron_ore","deepslate_iron_ore");
    static final Set<String> ORE_CONTEXT=union(ORES,ids("coal_ore","deepslate_coal_ore"));
    static final Set<String> AIR=ids("air","cave_air","void_air");
    static final Set<String> LEAVES=ids("oak_leaves","spruce_leaves","birch_leaves","jungle_leaves","acacia_leaves","dark_oak_leaves","mangrove_leaves");
    static final Set<String> FLOWERS=ids("dandelion","poppy","blue_orchid","allium","azure_bluet","red_tulip",
        "orange_tulip","white_tulip","pink_tulip","oxeye_daisy","cornflower","lily_of_the_valley");
    static final Set<String> PLANTS=union(FLOWERS,ids("short_grass","fern","tall_grass","large_fern","vine"));
    static final Set<String> TARGETS=union(LEGACY,LOGS,ORES);
    static final Set<String> CELLS=union(TARGETS,AIR,ORE_CONTEXT,LEAVES,PLANTS,ids("grass_block","bedrock","deepslate"));
    static boolean target(String id,JsonObject properties){return TARGETS.contains(id)&&properties(id,properties);}
    static boolean accepts(String id,String exactClass,JsonObject properties){
        return CELLS.contains(id)&&expectedClass(id).equals(exactClass)&&properties(id,properties);
    }
    static String expectedClass(String id){
        String name=AIR.contains(id)?"AirBlock":id.equals("minecraft:grass_block")?"GrassBlock":
            LOGS.contains(id)||id.equals("minecraft:deepslate")?"RotatedPillarBlock":ORE_CONTEXT.contains(id)?"DropExperienceBlock":
            id.equals("minecraft:mangrove_leaves")?"MangroveLeavesBlock":LEAVES.contains(id)?"LeavesBlock":FLOWERS.contains(id)?"FlowerBlock":
            id.equals("minecraft:short_grass")||id.equals("minecraft:fern")?"TallGrassBlock":
            id.equals("minecraft:tall_grass")||id.equals("minecraft:large_fern")?"DoublePlantBlock":
            id.equals("minecraft:vine")?"VineBlock":"Block";
        return "net.minecraft.world.level.block."+name;
    }
    static boolean properties(String id,JsonObject p){
        if(p==null||!CELLS.contains(id))return false;
        for(var entry:p.entrySet())if(!entry.getValue().isJsonPrimitive()||!entry.getValue().getAsJsonPrimitive().isString())return false;
        if(LOGS.contains(id)||id.equals("minecraft:deepslate"))return keys(p,"axis")&&one(p,"axis","x","y","z");
        if(id.equals("minecraft:grass_block"))return keys(p,"snowy")&&one(p,"snowy","true","false");
        if(LEAVES.contains(id))return keys(p,"distance","persistent","waterlogged")&&one(p,"distance","1","2","3","4","5","6","7")
            &&one(p,"persistent","true","false")&&one(p,"waterlogged","false");
        if(id.equals("minecraft:tall_grass")||id.equals("minecraft:large_fern"))return keys(p,"half")&&one(p,"half","upper","lower");
        if(id.equals("minecraft:vine"))return keys(p,"up","north","south","east","west")
            &&p.entrySet().stream().allMatch(e->Set.of("true","false").contains(e.getValue().getAsString()));
        return p.size()==0;
    }
    static boolean bodyClear(String id){return AIR.contains(id)||PLANTS.contains(id)&&!id.equals("minecraft:vine");}
    static boolean fullCube(String id){return CELLS.contains(id)&&!AIR.contains(id)&&!PLANTS.contains(id);}
    static boolean support(String id){return fullCube(id)&&!LEAVES.contains(id);}
    private static boolean keys(JsonObject p,String...keys){return p.keySet().equals(Set.of(keys));}
    private static boolean one(JsonObject p,String key,String...values){return Set.of(values).contains(p.get(key).getAsString());}
    private static Set<String> ids(String...names){return Stream.of(names).map(n->"minecraft:"+n).collect(Collectors.toUnmodifiableSet());}
    @SafeVarargs private static Set<String> union(Set<String>...sets){return Stream.of(sets).flatMap(Set::stream).collect(Collectors.toUnmodifiableSet());}
    private ScopedMiningCellPolicy(){}
}
