package io.github.campione01.mineclientbridge;

import java.util.Set;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.ai.goal.BreedGoal;
import net.minecraft.world.entity.ai.goal.ClimbOnTopOfPowderSnowGoal;
import net.minecraft.world.entity.ai.goal.FloatGoal;
import net.minecraft.world.entity.ai.goal.Goal;
import net.minecraft.world.entity.ai.goal.GoalSelector;
import net.minecraft.world.entity.ai.goal.LookAtPlayerGoal;
import net.minecraft.world.entity.ai.goal.TemptGoal;
import net.minecraft.world.entity.ai.goal.WaterAvoidingRandomStrollGoal;
import net.minecraft.world.entity.ai.goal.WrappedGoal;
import net.minecraft.world.entity.animal.Rabbit;

/** Read-only exact-vanilla Rabbit facts, called by the owning server-thread snapshot read. */
final class NativeRabbitObservation {
    static final int MAX_GOALS = 16;
    private static final Set<Class<?>> PASSIVE_GOALS = Set.of(FloatGoal.class, ClimbOnTopOfPowderSnowGoal.class,
            BreedGoal.class, TemptGoal.class, WaterAvoidingRandomStrollGoal.class, LookAtPlayerGoal.class);
    private static final Set<String> NESTED_PASSIVE_GOALS = Set.of(
            "net.minecraft.world.entity.animal.Rabbit$RabbitPanicGoal",
            "net.minecraft.world.entity.animal.Rabbit$RabbitAvoidEntityGoal",
            "net.minecraft.world.entity.animal.Rabbit$RaidGardenGoal");
    private NativeRabbitObservation() { }

    static NativeLivingSnapshot.RabbitState read(Mob mob) {
        if (mob.getClass() != Rabbit.class || mob.getType() != EntityType.RABBIT) return null;
        Rabbit rabbit = (Rabbit) mob;
        try {
            Integer raw = rabbit.getEntityData().get(Rabbit.DATA_TYPE_ID);
            if (raw == null) return null;
            Rabbit.Variant variant = rabbit.getVariant();
            // byId() falls back to BROWN for unknown raw IDs: that is not benign evidence.
            if (variant == null || raw != variant.id()) return null;
            Boolean passive = passiveGoals(rabbit);
            return passive == null ? null : new NativeLivingSnapshot.RabbitState(
                    raw, variant == Rabbit.Variant.EVIL, passive);
        } catch (RuntimeException unavailable) {
            return null;
        }
    }

    private static Boolean passiveGoals(Rabbit rabbit) {
        if (rabbit.goalSelector == null || rabbit.targetSelector == null
                || rabbit.goalSelector.getClass() != GoalSelector.class
                || rabbit.targetSelector.getClass() != GoalSelector.class) return null;
        int inspected = 0; boolean passive = true;
        // Inspect the complete registered inventories, not the currently running subset.
        for (WrappedGoal wrapper : rabbit.goalSelector.getAvailableGoals()) {
            if (++inspected > MAX_GOALS) return null;
            if (wrapper == null || wrapper.getClass() != WrappedGoal.class) return null;
            Goal goal = wrapper.getGoal();
            if (goal == null) return null;
            Class<?> type = goal.getClass();
            // Enclosing-class identity binds private nested names to this exact loaded Rabbit.
            if (!PASSIVE_GOALS.contains(type)
                    && !(type.getEnclosingClass() == Rabbit.class && NESTED_PASSIVE_GOALS.contains(type.getName()))) passive = false;
        }
        for (WrappedGoal wrapper : rabbit.targetSelector.getAvailableGoals()) {
            if (++inspected > MAX_GOALS) return null;
            if (wrapper == null || wrapper.getClass() != WrappedGoal.class || wrapper.getGoal() == null) return null;
            passive = false;
        }
        return passive;
    }
}
