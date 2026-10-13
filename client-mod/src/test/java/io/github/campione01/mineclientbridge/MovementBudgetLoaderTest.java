package io.github.campione01.mineclientbridge;

import java.lang.reflect.Field;
import net.minecraft.SharedConstants;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.level.entity.EntityInLevelCallback;
import net.minecraft.world.phys.Vec3;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import static org.junit.jupiter.api.Assertions.*;

/** Real production mixin injection under FML. No world/client/server or physics loop is constructed. */
@EnabledIfEnvironmentVariable(named="MDC_REAL_MOD_LOADER_TESTS",matches="true")
@Execution(ExecutionMode.SAME_THREAD)
class MovementBudgetLoaderTest {
    @BeforeAll static void bootstrap(){SharedConstants.tryDetectVersion();Bootstrap.bootStrap();}
    static final class AllocationPlayer extends LocalPlayer {
        private AllocationPlayer(){super(null,null,null,null,null,false,false);throw new AssertionError("Allocation only");}
        @Override public void setPos(double x,double y,double z){setPosRaw(x,y,z);}
        @Override protected void updateAutoJump(float x,float z){}
    }
    static void field(Class<?> cls,Object target,String name,Object value)throws Exception{Field f=cls.getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    static AllocationPlayer player()throws Exception {
        Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);
        var p=(AllocationPlayer)((sun.misc.Unsafe)f.get(null)).allocateInstance(AllocationPlayer.class);
        field(Entity.class,p,"position",new Vec3(0,64,0));field(Entity.class,p,"blockPosition",new BlockPos(0,64,0));
        field(Entity.class,p,"chunkPosition",new ChunkPos(0,0));field(Entity.class,p,"levelCallback",EntityInLevelCallback.NULL);
        p.noPhysics=true;return p; // Only bypasses irrelevant collision setup in this allocation-only test fixture.
    }
    MovementBudgetLedger arm(AllocationPlayer p)throws Exception{var b=new MovementBudgetLedger("bundle","session","world","uuid",new Object(),p,0,64,0,1);field(MovementBudget.class,null,"ledger",b);return b;}
    @AfterEach void clear()throws Exception{field(MovementBudget.class,null,"ledger",null);}
    @Test void actualVanillaSetPosRawInjectionRecordsSmallCorrection()throws Exception{var p=player();var b=arm(p);p.setPosRaw(.1,64,0);assertTrue(b.invalid());assertEquals(.1,b.distance());}
    @Test void actualVanillaMoveInjectionCapturesSameTickOutAndBack()throws Exception{var p=player();var b=arm(p);p.move(MoverType.SELF,new Vec3(.25,0,0));p.move(MoverType.SELF,new Vec3(-.25,0,0));assertEquals(.5,b.distance(),1e-12);assertTrue(b.usable());assertEquals(0,b.depth());}
    @Test void actualVanillaPistonMoveIsNeverAcceptedAsSelfMotion()throws Exception{var p=player();var b=arm(p);p.move(MoverType.PISTON,new Vec3(.1,0,0));assertTrue(b.invalid());assertEquals(.1,b.distance());}
    @Test void actualVanillaIgnoreFirstRecenterDoesNotInvalidateButRealDeltaDoes()throws Exception {
        Field unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
        var unsafe=(sun.misc.Unsafe)unsafeField.get(null);
        var mc=(net.minecraft.client.Minecraft)unsafe.allocateInstance(net.minecraft.client.Minecraft.class);
        var window=(com.mojang.blaze3d.platform.Window)unsafe.allocateInstance(com.mojang.blaze3d.platform.Window.class);
        field(com.mojang.blaze3d.platform.Window.class,window,"window",1L);
        field(net.minecraft.client.Minecraft.class,mc,"window",window);field(net.minecraft.client.Minecraft.class,mc,"windowActive",true);
        Field instance=net.minecraft.client.Minecraft.class.getDeclaredField("instance");instance.setAccessible(true);Object previous=instance.get(null);
        String isolation=System.getProperty("mineclientBridge.isolatedInput");
        try {
            instance.set(null,mc);System.setProperty("mineclientBridge.isolatedInput","false");
            var mouse=new net.minecraft.client.MouseHandler(mc);var p=player();var b=arm(p);
            Field dx=net.minecraft.client.MouseHandler.class.getDeclaredField("accumulatedDX");dx.setAccessible(true);
            var onMove=net.minecraft.client.MouseHandler.class.getDeclaredMethod("onMove",long.class,double.class,double.class);onMove.setAccessible(true);
            onMove.invoke(mouse,1L,400D,300D);assertEquals(0D,dx.getDouble(mouse));p.turn(0,0);assertTrue(b.usable(),"Vanilla ignoreFirstMove suppresses automatic recenter");
            onMove.invoke(mouse,1L,400D,300D);assertEquals(0D,dx.getDouble(mouse));p.turn(0,0);assertTrue(b.usable(),"An unchanged cursor has no effective delta");
            onMove.invoke(mouse,1L,401D,300D);assertEquals(1D,dx.getDouble(mouse));
            // Exact injected Entity.turn hook; MouseHandler client mixins cannot apply in SERVER-side forgejunitdev.
            p.turn(dx.getDouble(mouse),0);assertTrue(b.invalid(),"Actual nonzero player turn invalidates immediately");
        } finally {instance.set(null,previous);if(isolation==null)System.clearProperty("mineclientBridge.isolatedInput");else System.setProperty("mineclientBridge.isolatedInput",isolation);}
    }
    @Test void actualVanillaXpTypeIsAllowedOnlyAfterExactOutputPhase()throws Exception {
        Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);var unsafe=(sun.misc.Unsafe)f.get(null);
        var orb=(net.minecraft.world.entity.ExperienceOrb)unsafe.allocateInstance(net.minecraft.world.entity.ExperienceOrb.class);
        field(Entity.class,orb,"type",net.minecraft.world.entity.EntityType.EXPERIENCE_ORB);var b=arm(player());
        assertFalse(MovementBudget.allowedNearbyEntity(orb));b.allowFurnaceXp();assertTrue(MovementBudget.allowedNearbyEntity(orb));
        field(Entity.class,orb,"type",net.minecraft.world.entity.EntityType.ZOMBIE);assertFalse(MovementBudget.allowedNearbyEntity(orb));
    }
    @Test void unarmedDefaultHooksDoNotChangeVanillaPosition()throws Exception{var p=player();p.move(MoverType.SELF,new Vec3(.3,0,.4));assertEquals(.3,p.getX());assertEquals(.4,p.getZ());assertEquals("unarmed",MovementBudget.snapshot().get("status").getAsString());}
}
