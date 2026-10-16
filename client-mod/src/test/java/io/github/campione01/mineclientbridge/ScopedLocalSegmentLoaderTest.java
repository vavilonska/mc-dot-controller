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

/** Real Entity.move Mixin bootstrap; allocation-only receiver, not ordinary-world physics. */
@EnabledIfEnvironmentVariable(named="MDC_REAL_MOD_LOADER_TESTS",matches="true")
@Execution(ExecutionMode.SAME_THREAD)
class ScopedLocalSegmentLoaderTest {
    @BeforeAll static void bootstrap(){SharedConstants.tryDetectVersion();Bootstrap.bootStrap();}
    static final class AllocationPlayer extends LocalPlayer {
        private AllocationPlayer(){super(null,null,null,null,null,false,false);throw new AssertionError("Allocation only");}
        @Override public void setPos(double x,double y,double z){setPosRaw(x,y,z);}
        @Override protected void updateAutoJump(float x,float z){}
    }
    static sun.misc.Unsafe unsafe()throws Exception{Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);return(sun.misc.Unsafe)f.get(null);}
    static void field(Class<?> type,Object target,String name,Object value)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    static AllocationPlayer player()throws Exception{
        var p=(AllocationPlayer)unsafe().allocateInstance(AllocationPlayer.class);
        field(Entity.class,p,"position",new Vec3(0,64,0));field(Entity.class,p,"blockPosition",new BlockPos(0,64,0));
        field(Entity.class,p,"chunkPosition",new ChunkPos(0,0));field(Entity.class,p,"levelCallback",EntityInLevelCallback.NULL);
        p.noPhysics=true;return p;
    }
    @AfterEach void clear(){ScopedLocalSegmentDispatch.nextTick();}
    @Test void actualUnarmedMoveIsUnchangedAndProvesHookInstallation()throws Exception{
        var p=player();p.move(MoverType.SELF,new Vec3(.25,0,.5));
        assertEquals(.25,p.getX());assertEquals(.5,p.getZ());assertTrue(ScopedLocalSegmentDispatch.ready());
    }
    @Test void actualMoveRejectsOrphanTokenAndNextTickRestoresOrdinaryMotion()throws Exception{
        var p=player();p.move(MoverType.SELF,new Vec3(0,0,0));
        var owner=(ScopedLocalSegmentMovement)unsafe().allocateInstance(ScopedLocalSegmentMovement.class);
        field(ScopedLocalSegmentMovement.class,owner,"player",p);ScopedLocalSegmentDispatch.arm(owner);
        p.move(MoverType.SELF,new Vec3(.25,0,0));assertEquals(0,p.getX(),"missing exact owner rejects imminent move");
        p.move(MoverType.PISTON,new Vec3(.25,0,0));assertEquals(0,p.getX(),"same tick cannot borrow spent token");
        ScopedLocalSegmentDispatch.nextTick();p.move(MoverType.SELF,new Vec3(.25,0,0));assertEquals(.25,p.getX());
    }
}
