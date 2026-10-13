package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import org.junit.jupiter.api.Test;

class CoordinationGrassSupportTest {
    private static final ClientActionRequest.Point START=new ClientActionRequest.Point(.5,64,.5,false);
    private static final ClientActionRequest.Point END=new ClientActionRequest.Point(1.5,64,.5,false);
    private static FlatStepCorridor.Cell grass(int x,int y,int z) {
        boolean floor=y==63;
        return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                floor?"minecraft:grass_block":"minecraft:air",true,!floor,floor,"minecraft:empty",false);
    }
    private static String check(FlatStepCorridor.CellSource source) {
        return CoordinationStepPolicy.check(START,END,20,CoordinationStepGuardTest.state(0,true,.5,20),source);
    }
    @Test void fullGrassFloorClearsContinuousOneBlockCorridor() { assertNull(check(CoordinationGrassSupportTest::grass)); }
    @Test void whitelistChangesOnlyByAddingGrass() {
        assertEquals(Set.of("minecraft:stone","minecraft:cobblestone","minecraft:dirt","minecraft:grass_block"),CoordinationStepGuard.SUPPORT);
    }
    @Test void SnowOrVegetationAboveGrassStillRejects() {
        for (String id:new String[]{"minecraft:snow","minecraft:short_grass","minecraft:tall_grass"}) {
            assertNotNull(check((x,y,z)->y==64?new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,id,true,
                    !id.equals("minecraft:snow"),false,"minecraft:empty",false):grass(x,y,z)),id);
        }
    }
    @Test void grassRequiresKnownFullSupportEmptyFluidAndNoHazard() {
        var bad=new FlatStepCorridor.Cell[]{
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,"minecraft:grass_block",true,false,true,"minecraft:empty",false),
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:grass_block",false,false,true,"minecraft:empty",false),
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:grass_block",true,false,false,"minecraft:empty",false),
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:grass_block",true,false,true,"minecraft:water",false),
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:grass_block",true,false,true,"minecraft:empty",true),
            new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:granite",true,false,true,"minecraft:empty",false)};
        for(var cell:bad) assertNotNull(check((x,y,z)->y==63?cell:grass(x,y,z)),cell.toString());
    }
    @Test void entityAndAgeGuardsAreUnchangedOnGrass() {
        assertEquals("coordination_step_entity_nearby",CoordinationStepPolicy.check(START,END,20,
                CoordinationStepGuardTest.state(1,true,.5,20),CoordinationGrassSupportTest::grass));
        assertTrue(CoordinationStepPolicy.ageValid(0,-800_000_000));
        assertFalse(CoordinationStepPolicy.ageValid(0,-800_000_001));
    }
    @Test void emitActualNativeClassificationForPythonComparison() throws Exception {
        var output=new JsonObject();var ids=new com.google.gson.JsonArray();
        CoordinationStepGuard.SUPPORT.stream().sorted().forEach(ids::add);output.add("support_ids",ids);
        output.addProperty("full_grass_clear",check(CoordinationGrassSupportTest::grass)==null);
        var at=Path.of(System.getProperty("mineclientBridge.projectDir"),"build","validation","grass-support-wire.json");
        Files.createDirectories(at.getParent());Files.writeString(at,BridgeJson.toJson(output));
    }
}
