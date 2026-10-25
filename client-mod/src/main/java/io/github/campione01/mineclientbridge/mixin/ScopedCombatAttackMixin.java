package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedCombatDispatch;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
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
    private void mineclientBridge$combatAttackInstalled(CallbackInfo ci){ScopedCombatDispatch.attackInstalled();ScopedTargetDispatch.attackInstalled();ScopedTargetDispatch.useInstalled();ScopedTargetDispatch.useReplacementInstalled();ScopedTargetDispatch.releaseInstalled();io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch.useInstalled();}
    @Inject(method="attack",at=@At("HEAD"),cancellable=true,require=1)
    private void mineclientBridge$combatAttack(Player player,Entity target,CallbackInfo ci){if(ScopedCombatDispatch.defensiveActive()){ci.cancel();return;}ScopedTargetDispatch.beforeAttack(player,target,false);ScopedCombatDispatch.beforeAttack(player,target);}
    @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;attack(Lnet/minecraft/world/entity/Entity;)V"),require=1)
    private void mineclientBridge$combatLocalAttack(Player player,Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeAttack(player,target,true);ScopedCombatDispatch.beforeAttack(player,target);}
    @Inject(method="useItem",at=@At("HEAD"),cancellable=true,require=1)
    private void mineclientBridge$defensiveUse(Player player,net.minecraft.world.InteractionHand hand,
            org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable<net.minecraft.world.InteractionResult> ci){if(!ScopedTargetDispatch.beforeUse(player,hand,false,false)||!ScopedCombatDispatch.beforeUse(player,hand,false))ci.setReturnValue(net.minecraft.world.InteractionResult.FAIL);}
    @Inject(method="useItemOn",at=@At("HEAD"),cancellable=true,require=1)
    private void mineclientBridge$defensiveUseOn(net.minecraft.client.player.LocalPlayer player,net.minecraft.world.InteractionHand hand,
            net.minecraft.world.phys.BlockHitResult hit,org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable<net.minecraft.world.InteractionResult> ci){if(!ScopedTargetDispatch.beforeUse(player,hand,true,false)||!ScopedCombatDispatch.beforeUse(player,hand,true)){ci.setReturnValue(net.minecraft.world.InteractionResult.FAIL);return;}io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch.enterUse(player,hand,hit);}

    @Inject(method="lambda$useItem$5",at=@At(value="INVOKE",target="Lnet/minecraft/world/item/ItemStack;use(Lnet/minecraft/world/level/Level;Lnet/minecraft/world/entity/player/Player;Lnet/minecraft/world/InteractionHand;)Lnet/minecraft/world/InteractionResultHolder;"),require=1,remap=false)
    private void mineclientBridge$targetLocalUse(net.minecraft.world.InteractionHand hand,Player player,
            org.apache.commons.lang3.mutable.MutableObject<net.minecraft.world.InteractionResult> result,int sequence,
            org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable<net.minecraft.network.protocol.Packet<?>> ci){
        if(!ScopedTargetDispatch.beforeUse(player,hand,false,true))throw new IllegalStateException("target_local_use_refused");
    }
    @Inject(method="lambda$useItem$5",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;setItemInHand(Lnet/minecraft/world/InteractionHand;Lnet/minecraft/world/item/ItemStack;)V"),require=1,remap=false)
    private void mineclientBridge$targetUseReplacement(net.minecraft.world.InteractionHand hand,Player player,
            org.apache.commons.lang3.mutable.MutableObject<net.minecraft.world.InteractionResult> result,int sequence,
            org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable<net.minecraft.network.protocol.Packet<?>> ci){
        ScopedTargetDispatch.beforeUseReplacement(player);
    }
    @Inject(method="releaseUsingItem",at=@At("HEAD"),require=1)
    private void mineclientBridge$targetRelease(Player player,CallbackInfo ci){ScopedTargetDispatch.beforeRelease(player,false);}
    @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;resetAttackStrengthTicker()V"),require=1)
    private void mineclientBridge$targetGameModeCooldown(Player player,Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeMeleePostMutation(player);}
}
