package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedCombatDispatch;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.entity.Entity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(MultiPlayerGameMode.class)
public abstract class ScopedCombatAttackMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$combatAttackInstalled(CallbackInfo ci){ScopedCombatDispatch.attackInstalled();}
    @Inject(method="attack",at=@At("HEAD"),require=1)
    private void mineclientBridge$combatAttack(Player player,Entity target,CallbackInfo ci){ScopedCombatDispatch.beforeAttack(player,target);}
    @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;attack(Lnet/minecraft/world/entity/Entity;)V"),require=1)
    private void mineclientBridge$combatLocalAttack(Player player,Entity target,CallbackInfo ci){ScopedCombatDispatch.beforeAttack(player,target);}
}
