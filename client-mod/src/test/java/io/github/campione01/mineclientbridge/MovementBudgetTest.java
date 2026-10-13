package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Pure ledger/wire tests. Real mixin application is tested separately under FML. */
class MovementBudgetTest {
    private final Object world=new Object(),player=new Object();
    MovementBudgetLedger ledger(){return new MovementBudgetLedger("bundle","session","generation","uuid",world,player,0,64,0,1);}
    void move(MovementBudgetLedger b,double x,double y,double z){b.beginTick();b.beginMove(true,.55,-.0784,0);b.position(x,y,z);b.endMove();}
    void sample(MovementBudgetLedger b,double x,boolean settled){b.sample(world,player,"session",x,64,0,settled,true);}
    JsonObject start(){JsonObject b=CapabilityGuardTest.request("movement_budget_start");b.add("movement_budget",JsonParser.parseString("{\"schema_version\":1,\"bundle_id\":\"bundle\",\"max_distance\":32,\"mode\":\"dry_flat_self_walk_v1\"}"));return b;}
    @Test void startIsExplicitGuardedNoInputAction(){assertEquals("movement_budget_start",ClientActionRequest.parse(start()).action());}
    @Test void capAndModeAreExact(){for(String field:new String[]{"schema_version","bundle_id","max_distance","mode"}){JsonObject b=start();b.getAsJsonObject("movement_budget").remove(field);assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}JsonObject b=start();b.getAsJsonObject("movement_budget").addProperty("max_distance",33);assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}
    @Test void capRejectsStringAndFraction(){for(String n:new String[]{"\"32\"","32.5","null","true"}){JsonObject b=start();b.getAsJsonObject("movement_budget").add("max_distance",JsonParser.parseString(n));assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}}
    @Test void wrongActionCannotCarryStartPayload(){JsonObject b=start();b.addProperty("action","select_hotbar");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}
    @Test void finishNeedsBindingAndCapabilityGuard(){JsonObject b=CapabilityGuardTest.request("movement_budget_finish");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));b.addProperty("movement_budget_bundle_id","bundle");assertEquals("movement_budget_finish",ClientActionRequest.parse(b).action());b.remove("capability_guard");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}
    @Test void sameTickBacktrackingCountsBothDirections(){var b=ledger();b.beginMove(true,.25,0,0);b.position(.25,64,0);b.endMove();b.beginMove(true,-.25,0,0);b.position(0,64,0);b.endMove();assertEquals(.5,b.distance(),1e-12);assertTrue(b.usable());}
    @Test void excessiveSameTickSelfMotionIsNotHiddenByManySmallMoves(){var b=ledger();for(int n=1;n<=6;n++){b.beginMove(true,.1,0,0);b.position(n*.1,64,0);b.endMove();}assertTrue(b.invalid());assertEquals(.6,b.distance(),1e-12);}
    @Test void firstInvalidationReasonCannotBeErased(){var b=ledger();b.invalidate("first");b.invalidate("second");assertEquals("first",b.reason());}
    @Test void diagonalUsesThreeDimensionalPolylineNotEndpointTotals(){var b=ledger();move(b,.3,64,.4);move(b,0,64,0);assertEquals(1,b.distance(),1e-12);}
    @Test void verticalDisplacementIsRecordedAndInvalidatesFlatEnvelope(){var b=ledger();move(b,0,64.25,0);assertEquals(.25,b.distance());assertTrue(b.invalid());}
    @Test void noActionBoundaryResetExists(){var b=ledger();for(int n=1;n<=20;n++){move(b,n*.3,64,0);sample(b,n*.3,false);}assertEquals(6,b.distance(),1e-10);assertEquals("bundle",b.snapshot().get("bundle_id").getAsString());}
    @Test void reserveStopsBeforeExhaustionAndKeepsCountingCoast(){var b=ledger();for(int n=1;n<=60;n++)move(b,n*.5,64,0);assertTrue(b.stopping());assertEquals(30,b.distance());move(b,30.3,64,0);assertTrue(b.stopping());assertEquals(30.3,b.distance());}
    @Test void reserveDominatesOneNextTickAndAllNeutralCoasting(){double future=.55;for(int n=1;n<=1000;n++)future+=.55*Math.pow(.55,n);assertTrue(future<MovementBudgetLedger.RESERVE);assertEquals(.55/(1-.55),future,1e-10);}
    @Test void externalMoveInvalidatesEvenWhenSmall(){var b=ledger();b.beginMove(false,.01,0,0);b.position(.01,64,0);b.endMove();assertTrue(b.invalid());assertFalse(b.snapshot().get("coverage_complete").getAsBoolean());}
    @Test void rawCorrectionNeverAcceptedAsSelfMove(){var b=ledger();b.position(.001,64,0);assertTrue(b.invalid());assertEquals(.001,b.distance());}
    @Test void missingHookCoverageNeverGuessesDistance(){var b=ledger();sample(b,3,false);assertTrue(b.invalid());assertEquals(0,b.distance());}
    @Test void contextWorldPlayerSessionCannotRebind(){for(int n=0;n<3;n++){var b=ledger();b.sample(n==0?new Object():world,n==1?new Object():player,n==2?"other":"session",0,64,0,true,true);assertTrue(b.invalid());sample(b,0,true);assertTrue(b.invalid());}}
    @Test void reentrantAndUnfinishedMovesInvalidate(){var b=ledger();b.beginMove(true,.1,0,0);b.beginMove(true,.1,0,0);assertTrue(b.invalid());b=ledger();b.beginMove(true,.1,0,0);sample(b,0,true);assertTrue(b.invalid());}
    @Test void secondPositionMutationInSameVanillaMoveInvalidates(){var b=ledger();b.beginMove(true,.3,0,0);b.position(.1,64,0);b.position(.2,64,0);b.endMove();assertTrue(b.invalid());assertEquals(.2,b.distance());}
    @Test void invalidVelocityAndStepNeverRemainUsable(){for(double value:new double[]{Double.NaN,Double.POSITIVE_INFINITY,.56}){var b=ledger();b.beginMove(true,value,0,0);assertTrue(b.invalid());}}
    @Test void frictionCannotSilentlyIncreaseAcceleration(){assertTrue(MovementBudget.ordinaryFriction(.6F));for(float friction:new float[]{0,.1F,.599F,.61F,Float.NaN,Float.POSITIVE_INFINITY})assertFalse(MovementBudget.ordinaryFriction(friction));}
    @Test void coordinateOverflowProducesInvalidFiniteDiagnostic(){var b=new MovementBudgetLedger("bundle","session","world","uuid",world,player,1e308,64,0,1);b.position(-1e308,64,0);assertTrue(b.invalid());assertEquals(0,b.distance());}
    @Test void capCannotBeOverspentAndReportedValid(){var b=ledger();for(int n=1;n<=65;n++)move(b,n*.5,64,0);assertTrue(b.invalid());assertEquals(32.5,b.distance());}
    @Test void finishRequiresThreeSettledPostTicks(){var b=ledger();for(int n=0;n<2;n++)sample(b,0,true);assertThrows(ClientActionRequest.Rejected.class,()->b.seal(2));sample(b,0,true);assertTrue(b.canSeal());b.seal(3);assertEquals("sealed",b.snapshot().get("status").getAsString());}
    @Test void sealedTelemetryImmutableAfterBoundary(){var b=ledger();for(int n=0;n<3;n++)sample(b,0,true);b.seal(2);JsonObject sealed=b.snapshot();assertThrows(ClientActionRequest.Rejected.class,()->b.seal(3));b.sample(new Object(),new Object(),"new",100,0,0,false,true);b.position(4,5,6);b.invalidate("late");assertEquals(sealed,b.snapshot());}
    @Test void invalidLedgerCannotSealEvenWhenStationary(){var b=ledger();b.invalidate("uncertain");for(int n=0;n<3;n++)sample(b,0,true);assertThrows(ClientActionRequest.Rejected.class,()->b.seal(2));}
    @Test void actionIdRetriesDoNotRepeatStart(){ActionRegistry r=new ActionRegistry();var request=ClientActionRequest.parse(start());var first=r.begin(request);r.finishAfterCleanup("succeeded","movement_budget_started",true);assertSame(first,r.existing(request));JsonObject changed=start();changed.getAsJsonObject("movement_budget").addProperty("bundle_id","other");assertThrows(ClientActionRequest.Rejected.class,()->r.existing(ClientActionRequest.parse(changed)));}
    @Test void furnaceXpPhaseRequiresExactGuardedSingleIronOutputQuickMove(){
        JsonObject b=CapabilityGuardTest.request("click_slot");b.addProperty("container_id",1);b.addProperty("slot",2);b.addProperty("button",0);b.addProperty("click_type","quick_move");
        b.addProperty("expected_menu_class","net.minecraft.world.inventory.FurnaceMenu");b.addProperty("expected_menu_state_id",1);
        b.add("expected_slot_item",JsonParser.parseString("{\"item_fingerprint\":\"fingerprint\",\"id\":\"minecraft:iron_ingot\",\"count\":1}"));b.add("expected_carried",JsonParser.parseString("{\"item_fingerprint\":\"empty\"}"));
        assertTrue(MovementBudget.furnaceOutputRequest(ClientActionRequest.parse(b)));
        b.getAsJsonObject("expected_slot_item").addProperty("count",2);assertFalse(MovementBudget.furnaceOutputRequest(ClientActionRequest.parse(b)));
        b.getAsJsonObject("expected_slot_item").addProperty("count",1);b.addProperty("slot",1);assertFalse(MovementBudget.furnaceOutputRequest(ClientActionRequest.parse(b)));
        b.addProperty("slot",2);b.addProperty("click_type","pickup");assertFalse(MovementBudget.furnaceOutputRequest(ClientActionRequest.parse(b)));
        b.addProperty("click_type","quick_move");b.addProperty("expected_menu_class","net.minecraft.world.inventory.BlastFurnaceMenu");assertFalse(MovementBudget.furnaceOutputRequest(ClientActionRequest.parse(b)));
    }
    private void callbackCase(boolean isolated,boolean synthetic,boolean armed,boolean expectedAccepted,boolean expectedInvalid)throws Exception {
        String previous=System.getProperty("mineclientBridge.isolatedInput");
        var field=MovementBudget.class.getDeclaredField("ledger");field.setAccessible(true);Object previousLedger=field.get(null);var b=ledger();
        try {
            System.setProperty("mineclientBridge.isolatedInput",Boolean.toString(isolated));field.set(null,armed?b:null);
            if(synthetic)ClientInputIsolation.syntheticDispatch(()->assertEquals(expectedAccepted,MovementBudget.acceptsInputCallback()));
            else assertEquals(expectedAccepted,MovementBudget.acceptsInputCallback());
            assertEquals(expectedInvalid,b.invalid());
        } finally {field.set(null,previousLedger);if(previous==null)System.clearProperty("mineclientBridge.isolatedInput");else System.setProperty("mineclientBridge.isolatedInput",previous);}
    }
    @Test void acceptedManualCallbackInvalidatesBeforeNextSample()throws Exception {callbackCase(false,false,true,true,true);}
    @Test void blockedIsolationCallbackDoesNotPerturbAcceptedWalking()throws Exception {callbackCase(true,false,true,false,false);}
    @Test void syntheticBridgeCallbackPreservesExistingSemantics()throws Exception {callbackCase(true,true,true,true,false);callbackCase(false,true,true,true,false);}
    @Test void unarmedNativeCallbacksPreserveDefaultBehavior()throws Exception {callbackCase(false,false,false,true,false);callbackCase(true,false,false,false,false);}
    @Test void allFiveNativeCallbackEntrypointsUseBudgetAwareIsolation()throws Exception {
        Path source=Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/mixin");
        String mouse=Files.readString(source.resolve("MouseHandlerMixin.java")),keyboard=Files.readString(source.resolve("KeyboardHandlerMixin.java"));
        assertEquals(2,mouse.split("MovementBudget.acceptsInputCallback",-1).length-1);String entity=Files.readString(source.resolve("EntityMovementBudgetMixin.java"));assertTrue(entity.contains("MovementBudget.effectivePlayerTurn"));assertTrue(entity.contains("turn(DD)V"));assertEquals(2,keyboard.split("MovementBudget.acceptsInputCallback",-1).length-1);
    }
    @Test void observationHooksNeverOverridePhysicsAndRunAtPositionWrite()throws Exception {String s=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/mixin/EntityMovementBudgetMixin.java"));assertTrue(s.contains("opcode=181,shift=At.Shift.AFTER"));assertFalse(s.contains("cancellable"));assertFalse(s.contains("setDeltaMovement"));assertFalse(s.contains("setPos("));}
}
