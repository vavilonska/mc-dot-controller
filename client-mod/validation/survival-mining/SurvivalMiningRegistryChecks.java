package io.github.campione01.mineclientbridge;
import java.nio.file.*;
import java.util.*;
import com.google.gson.*;
import net.minecraft.SharedConstants;
import net.minecraft.server.Bootstrap;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.level.EmptyBlockGetter;

/** Registry/shape bootstrap only: no client/server entrypoint, player, world, socket or action. */
final class SurvivalMiningRegistryChecks {
    public static void main(String[] args)throws Exception {
        SharedConstants.tryDetectVersion();Bootstrap.bootStrap();int states=0;
        for(String id:new TreeSet<>(ScopedMiningCellPolicy.CELLS)){
            var block=BuiltInRegistries.BLOCK.get(ResourceLocation.parse(id));
            for(var state:block.getStateDefinition().getPossibleStates()){
                var properties=ScopedMining.properties(state);
                // Wet leaves are intentionally not admitted.
                if(properties.has("waterlogged")&&properties.get("waterlogged").getAsString().equals("true"))continue;
                if(!ScopedMining.exactCellState(state))throw new AssertionError("real state rejected "+state+" "+block.getClass());
                boolean full=state.isCollisionShapeFullBlock(EmptyBlockGetter.INSTANCE,BlockPos.ZERO);
                boolean empty=state.getCollisionShape(EmptyBlockGetter.INSTANCE,BlockPos.ZERO).isEmpty();
                if(full!=ScopedMiningCellPolicy.fullCube(id)||empty==full)throw new AssertionError("real collision differs "+state);
                states++;
            }
        }
        Files.writeString(Path.of(args[0]),"{\"status\":\"passed\",\"registry_states_checked\":"+states+",\"live_game\":false}",StandardOpenOption.CREATE_NEW);
        System.out.println("PASS "+states+" real vanilla registry states and collision shapes; no world or game started");
    }
}
