#!/usr/bin/env python3
"""Execute production dispatch hook methods with test doubles, no Minecraft launch.

This covers dispatch ownership/races and budget/lifetime mechanics. It does not
claim a mixin was loaded or a game-local side effect actually took place.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile

ROOT=Path(__file__).resolve().parents[2]
PKG='io/github/campione01/mineclientbridge'
STUBS={
'net/minecraft/client/Minecraft.java':'''package net.minecraft.client; public class Minecraft {private static final Minecraft M=new Minecraft(); public static Minecraft getInstance(){return M;}}''',
'net/minecraft/world/InteractionHand.java':'''package net.minecraft.world; public enum InteractionHand {MAIN_HAND,OFF_HAND}''',
'net/minecraft/world/phys/Vec3.java':'''package net.minecraft.world.phys; public class Vec3 {}''',
'net/minecraft/world/entity/Entity.java':'''package net.minecraft.world.entity; public class Entity {public int id=9;public int getId(){return id;}}''',
'net/minecraft/world/entity/LivingEntity.java':'''package net.minecraft.world.entity; public class LivingEntity extends Entity {}''',
'net/minecraft/world/item/Items.java':'''package net.minecraft.world.item; public class Items {public static final Object BOW=new Object(),SHIELD=new Object(),ARROW=new Object();}''',
'net/minecraft/world/item/ItemStack.java':'''package net.minecraft.world.item; public class ItemStack {public Object item;public Object getItem(){return item;}public boolean is(Object expected){return item==expected;}}''',
'net/minecraft/world/entity/player/Player.java':'''package net.minecraft.world.entity.player; import net.minecraft.world.InteractionHand; import net.minecraft.world.item.ItemStack; public class Player extends net.minecraft.world.entity.LivingEntity {public boolean using;public InteractionHand hand=InteractionHand.MAIN_HAND;public ItemStack stack=new ItemStack(),ammo=new ItemStack();public ItemStack getItemInHand(InteractionHand hand){return stack;}public Runnable projectileHook;public ItemStack projectileOverride;public ItemStack getProjectile(ItemStack weapon){if(projectileHook!=null){Runnable h=projectileHook;projectileHook=null;h.run();}if(projectileOverride!=null)return projectileOverride;ammo.item=net.minecraft.world.item.Items.ARROW;return ammo;}public float yaw,pitch;public boolean isUsingItem(){return using;}public InteractionHand getUsedItemHand(){return hand;}public ItemStack getUseItem(){return stack;}public float getYRot(){return yaw;}public float getXRot(){return pitch;}}''',
'net/minecraft/network/protocol/Packet.java':'''package net.minecraft.network.protocol; public interface Packet<T> {}''',
'net/minecraft/network/protocol/game/ServerboundInteractPacket.java':'''package net.minecraft.network.protocol.game; import net.minecraft.world.InteractionHand;import net.minecraft.world.phys.Vec3;public class ServerboundInteractPacket implements net.minecraft.network.protocol.Packet<Object>,io.github.campione01.mineclientbridge.mixin.ScopedCombatInteractAccessor {public int id=9;public boolean secondary;private interface Action {void dispatch(Handler h);}private static final Action ATTACK_ACTION=new Action(){public void dispatch(Handler h){h.onAttack();}};private final Action action=ATTACK_ACTION;public static int maliciousCalls;public void replaceAction(){try{var f=ServerboundInteractPacket.class.getDeclaredField("action");f.setAccessible(true);f.set(this,new Action(){public void dispatch(Handler h){maliciousCalls++;h.onAttack();}});}catch(Exception e){throw new RuntimeException(e);}}public boolean isUsingSecondaryAction(){return secondary;}public int mineclientBridge$entityId(){return id;}public interface Handler {void onAttack();void onInteraction(InteractionHand h);void onInteraction(InteractionHand h,Vec3 p);}public void dispatch(Handler h){action.dispatch(h);}}''',
'net/minecraft/network/protocol/game/ServerboundPlayerActionPacket.java':'''package net.minecraft.network.protocol.game;public class ServerboundPlayerActionPacket implements net.minecraft.network.protocol.Packet<Object> {public enum Action {RELEASE_USE_ITEM,OTHER}public Action action=Action.RELEASE_USE_ITEM;public Action getAction(){return action;}}''',
'net/minecraft/network/protocol/game/ServerboundSetCarriedItemPacket.java':'''package net.minecraft.network.protocol.game;public class ServerboundSetCarriedItemPacket implements net.minecraft.network.protocol.Packet<Object> {public int slot;public int getSlot(){return slot;}}''',
'net/minecraft/network/protocol/game/ServerboundSwingPacket.java':'''package net.minecraft.network.protocol.game;public class ServerboundSwingPacket implements net.minecraft.network.protocol.Packet<Object> {public net.minecraft.world.InteractionHand getHand(){return net.minecraft.world.InteractionHand.MAIN_HAND;}}''',
'net/minecraft/network/protocol/game/ServerboundUseItemPacket.java':'''package net.minecraft.network.protocol.game;public class ServerboundUseItemPacket implements net.minecraft.network.protocol.Packet<Object> {public net.minecraft.world.InteractionHand hand=net.minecraft.world.InteractionHand.MAIN_HAND;public float yaw,pitch;public net.minecraft.world.InteractionHand getHand(){return hand;}public float getYRot(){return yaw;}public float getXRot(){return pitch;}}''',
'net/minecraft/network/protocol/game/ServerboundUseItemOnPacket.java':'''package net.minecraft.network.protocol.game;public class ServerboundUseItemOnPacket implements net.minecraft.network.protocol.Packet<Object> {}''',
PKG+'/mixin/ScopedCombatInteractAccessor.java':'''package io.github.campione01.mineclientbridge.mixin;public interface ScopedCombatInteractAccessor {int mineclientBridge$entityId();}''',
PKG+'/ClientActionRequest.java':'''package io.github.campione01.mineclientbridge;class ClientActionRequest {static class Rejected extends RuntimeException {Rejected(int code,String reason){super(reason);}}}''',
'net/minecraft/world/damagesource/DamageSource.java':'''package net.minecraft.world.damagesource;public class DamageSource {public net.minecraft.world.entity.Entity entity;public net.minecraft.world.entity.Entity getEntity(){return entity;}public net.minecraft.world.entity.Entity getDirectEntity(){return entity;}}''',
PKG+'/CapabilityItemBinding.java':'''package io.github.campione01.mineclientbridge;class CapabilityItemBinding {static boolean same(net.minecraft.world.item.ItemStack a,net.minecraft.world.item.ItemStack b){return a.item==b.item;}}''',
PKG+'/ActionRegistry.java':'''package io.github.campione01.mineclientbridge;class ActionRegistry {static class Entry {}}''',
PKG+'/ClientActions.java':'''package io.github.campione01.mineclientbridge;class ClientActions {static ScopedTargetAction owner,cleanup;static boolean ownsScopedTarget(ScopedTargetAction g,ActionRegistry.Entry e){return owner==g&&g.entry==e&&g.valid;}static boolean terminalTargetCleanup(ScopedTargetAction g,ActionRegistry.Entry e){return cleanup==g&&owner==g&&g.entry==e&&g.valid;}static ScopedTargetAction activeScopedTarget(){return owner;}}''',
PKG+'/CapabilityTargetAction.java':'''package io.github.campione01.mineclientbridge;class CapabilityTargetAction {ScopedTargetAction g;CapabilityTargetAction(ScopedTargetAction g){this.g=g;}ScopedTargetAction scoped(){return g;}net.minecraft.world.entity.Entity hitTarget(){return g.head==null?g.target:g.head;}}''',
PKG+'/ScopedTargetAction.java':'''package io.github.campione01.mineclientbridge;import net.minecraft.client.Minecraft;import net.minecraft.world.entity.player.Player;import net.minecraft.world.entity.Entity;class ScopedTargetAction {static class Level {long tick=100;long getGameTime(){return tick;}}Player player=new Player();Entity target=new Entity(),head;Level level=new Level();ActionRegistry.Entry entry=new ActionRegistry.Entry();TargetActionEffectBudget budget;CapabilityTargetAction action=new CapabilityTargetAction(this);int selected,geometry;Runnable finalHook;boolean valid=true,unknown,safe=true,externalIdle=true;long deadline=System.nanoTime()+5_000_000_000L;Runnable hook;ScopedTargetAction(boolean ranged,boolean shield){budget=new TargetActionEffectBudget(ranged,shield);ClientActions.owner=this;}CapabilityTargetAction action(){return action;}int geometry(){return geometry;}void geometryUnchanged(int before){require(before==geometry,"geometry_changed");rawBound(Minecraft.getInstance());}void finalExternalFence(int before){if(finalHook!=null){Runnable h=finalHook;finalHook=null;h.run();}geometryUnchanged(before);require(externalIdle,"external_owner_started");}void afterMelee(Minecraft mc){rawBound(mc);require(safe,"post_policy_changed");}void beforeEffect(Minecraft mc,TargetActionEffectBudget.Effect effect){rawBound(mc);require(safe,"species_or_collateral_changed");if(hook!=null){Runnable h=hook;hook=null;h.run();}rawBound(mc);}void rawBound(Minecraft mc){require(ClientActions.ownsScopedTarget(this,entry)&&System.nanoTime()<deadline,"owner_or_deadline");}void cleanupFence(Minecraft mc){require(ClientActions.terminalTargetCleanup(this,entry),"cleanup_owner");}record StackGeometry(net.minecraft.world.item.ItemStack stack,Object item){}static StackGeometry argumentStack(net.minecraft.world.item.ItemStack s){require(s!=null&&s.getClass()==net.minecraft.world.item.ItemStack.class,"argument_reader");return new StackGeometry(s,s.item);}static void unchangedArgument(StackGeometry b,net.minecraft.world.item.ItemStack a){require(b.stack==a&&b.item==a.item,"argument_changed");}void unknown(){unknown=true;budget.poison();}static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}}''',
}
CHECKS=r'''package io.github.campione01.mineclientbridge;
import net.minecraft.network.protocol.game.*;import net.minecraft.world.InteractionHand;import net.minecraft.world.item.Items;
import static io.github.campione01.mineclientbridge.TargetActionEffectBudget.Effect;
public final class ScopedTargetHookChecks {
 public static class BaseReader {public int getHealth(){return 20;}public int getId(){return 9;}}
 public static class SafeReader extends BaseReader {}
 public static class MutatingReader extends BaseReader {static int calls;public int getHealth(){calls++;return 20;}}
 public static class EvilComponent {public boolean equals(Object ignored){throw new AssertionError("component equals must not execute");}public int hashCode(){throw new AssertionError("component hashCode must not execute");}}
 static int checks;static void ok(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
 static void denied(Runnable r){boolean no=false;try{r.run();}catch(RuntimeException ex){no=true;}ok(no);}
 static void melee(ScopedTargetAction g,Runnable between){ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   ScopedTargetDispatch.beforeAttack(g.player,g.target,false);var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);
   between.run();ScopedTargetDispatch.send(p);ScopedTargetDispatch.beforeAttack(g.player,g.target,true);ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ScopedTargetDispatch.beforeMeleePostMutation(g.player);});}
 static void draw(ScopedTargetAction g){g.player.stack.item=Items.BOW;ScopedTargetDispatch.run(g.action,Effect.DRAW,()->{
   ok(ScopedTargetDispatch.beforeUse(g.player,InteractionHand.MAIN_HAND,false,false));
   ok(ScopedTargetDispatch.beforeUse(g.player,InteractionHand.MAIN_HAND,false,true));ScopedTargetDispatch.beforeStartUseMutation(g.player,InteractionHand.MAIN_HAND,g.player.stack,72000);g.player.using=true;g.player.stack.item=Items.BOW;
   var p=new ServerboundUseItemPacket();ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);});}
 static void release(ScopedTargetAction g,Runnable afterHead){ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
   ScopedTargetDispatch.beforeRelease(g.player,false);var p=new ServerboundPlayerActionPacket();ScopedTargetDispatch.packet(p);
   afterHead.run();ScopedTargetDispatch.send(p);ScopedTargetDispatch.beforeRelease(g.player,true);ScopedTargetDispatch.beforeBowDraw(g.player.stack,g.player.getProjectile(g.player.stack),g.player);
   ScopedTargetDispatch.beforeStopUsing(g.player);ScopedTargetDispatch.beforeStopMutation(g.player);g.player.using=false;});}
 public static void main(String[] args)throws Exception{
   ok(TargetActionReaderPolicy.declaredBy(SafeReader.class,"getHealth",BaseReader.class));
   ok(!TargetActionReaderPolicy.declaredBy(MutatingReader.class,"getHealth",BaseReader.class));
   ok(MutatingReader.calls==0);
   ok(!TargetActionReaderPolicy.declaredBy(SafeReader.class,"unknown",BaseReader.class));
   var evil=new EvilComponent();ok(TargetActionReaderPolicy.sameIdentityValues(java.util.List.of(evil),java.util.List.of(evil)));
   ok(!TargetActionReaderPolicy.sameIdentityValues(java.util.List.of(evil),java.util.List.of(new EvilComponent())));
   ScopedTargetDispatch.attackInstalled();ScopedTargetDispatch.useInstalled();ScopedTargetDispatch.releaseInstalled();ScopedTargetDispatch.releaseLocalInstalled();ScopedTargetDispatch.packetInstalled();ScopedTargetDispatch.sendInstalled();
   ok(!ScopedTargetDispatch.ready());ScopedTargetDispatch.stopLocalInstalled();ScopedTargetDispatch.startLocalInstalled();ScopedTargetDispatch.bowLocalInstalled();ScopedTargetDispatch.meleeLocalInstalled();ScopedTargetDispatch.meleePostInstalled();ScopedTargetDispatch.meleeSecondaryInstalled();ok(!ScopedTargetDispatch.ready());ScopedTargetDispatch.meleeInvulnerabilityInstalled();ok(!ScopedTargetDispatch.ready());ScopedTargetDispatch.useReplacementInstalled();ok(ScopedTargetDispatch.ready());
   {var g=new ScopedTargetAction(false,false);melee(g,()->{});ok(g.budget.local(Effect.MELEE)==1&&g.budget.packets(Effect.MELEE)==1&&!g.unknown);denied(()->melee(g,()->{}));}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->ClientActions.owner=null));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0&&g.budget.local(Effect.MELEE)==0);denied(()->melee(g,()->{}));}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->g.deadline=0));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->g.level.tick++));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);melee(g,()->{try{Thread.sleep(60);}catch(Exception e){throw new RuntimeException(e);}});ok(!g.unknown);ok(g.budget.packets(Effect.MELEE)==1&&g.budget.local(Effect.MELEE)==1);}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->g.externalIdle=false));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->g.safe=false));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->melee(g,()->g.hook=()->g.geometry++));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   for(String input:new String[]{"fire_resistance","poison","frozen","cooldown","use_duration","reach","selected_slot","inventory","carried","mapping","shelter_roof","bow_corridor","abilities","calm_observation"}){
     var g=new ScopedTargetAction(false,false);
     denied(()->melee(g,()->g.finalHook=()->g.geometry++));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0&&g.budget.local(Effect.MELEE)==0);
   }
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
      var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);g.finalHook=()->p.id=10;ScopedTargetDispatch.send(p);}));
      ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
      var p=new ServerboundInteractPacket();p.secondary=true;ScopedTargetDispatch.packet(p);}));ok(g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->ScopedTargetDispatch.packet(new ServerboundInteractPacket(){})));
      ok(g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
      var p=new ServerboundInteractPacket();p.replaceAction();ScopedTargetDispatch.packet(p);}));
      ok(g.budget.packets(Effect.MELEE)==0&&ServerboundInteractPacket.maliciousCalls==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
      var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);g.finalHook=p::replaceAction;ScopedTargetDispatch.send(p);}));
      ok(g.budget.packets(Effect.MELEE)==0&&ServerboundInteractPacket.maliciousCalls==0);}
   {var g=new ScopedTargetAction(true,false);g.player.stack.item=Items.BOW;
      denied(()->ScopedTargetDispatch.run(g.action,Effect.DRAW,()->{var stack=g.player.stack;
        g.finalHook=()->{g.player.stack=new net.minecraft.world.item.ItemStack();g.player.stack.item=Items.BOW;};
        ScopedTargetDispatch.beforeStartUseMutation(g.player,InteractionHand.MAIN_HAND,stack,72000);}));ok(g.budget.local(Effect.DRAW)==0);}
   {var g=new ScopedTargetAction(true,true);g.player.using=true;g.player.hand=InteractionHand.OFF_HAND;g.player.stack.item=Items.SHIELD;
      g.budget.reserve(Effect.SHIELD_USE);g.budget.chargeLocal(Effect.SHIELD_USE);g.budget.chargePacket(Effect.SHIELD_USE);
      denied(()->ScopedTargetDispatch.run(g.action,Effect.SHIELD_RELEASE,()->{
        g.finalHook=()->{g.player.stack=new net.minecraft.world.item.ItemStack();g.player.stack.item=Items.SHIELD;};
        ScopedTargetDispatch.beforeRelease(g.player,true);}));ok(g.budget.local(Effect.SHIELD_RELEASE)==0);}
   for(boolean changeObject:new boolean[]{false,true}){
      var g=new ScopedTargetAction(true,false);draw(g);denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
        var weapon=g.player.stack;var ammo=g.player.getProjectile(weapon);
        g.player.projectileHook=()->{if(changeObject){g.player.stack=new net.minecraft.world.item.ItemStack();g.player.stack.item=Items.BOW;}else weapon.item=Items.SHIELD;};
        ScopedTargetDispatch.beforeBowDraw(weapon,ammo,g.player);}));ok(g.budget.local(Effect.BOW_RELEASE)==0);
   }
   {var g=new ScopedTargetAction(true,false);draw(g);denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
      var weapon=g.player.stack;var ammo=g.player.getProjectile(weapon);
      g.finalHook=()->{g.player.stack=new net.minecraft.world.item.ItemStack();g.player.stack.item=Items.BOW;};
      ScopedTargetDispatch.beforeBowDraw(weapon,ammo,g.player);}));ok(g.budget.local(Effect.BOW_RELEASE)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
      var ammo=new net.minecraft.world.item.ItemStack();ammo.item=Items.ARROW;g.player.projectileOverride=ammo;
      g.player.projectileHook=()->ammo.item=Items.SHIELD;
      ScopedTargetDispatch.beforeBowDraw(g.player.stack,ammo,g.player);}));ok(g.budget.local(Effect.BOW_RELEASE)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
      var ammo=g.player.getProjectile(g.player.stack);g.finalHook=()->ammo.item=Items.SHIELD;
      ScopedTargetDispatch.beforeBowDraw(g.player.stack,ammo,g.player);}));ok(g.budget.local(Effect.BOW_RELEASE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{var p=new ServerboundInteractPacket();p.id=10;ScopedTargetDispatch.packet(p);}));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);ScopedTargetDispatch.send(p);}));ok(g.unknown&&g.budget.packets(Effect.MELEE)==1);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);}));ok(g.unknown&&g.budget.local(Effect.MELEE)==1);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->ScopedTargetDispatch.send(new ServerboundInteractPacket())));ok(g.unknown&&g.budget.packets(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{})));ok(g.unknown);}
   {var g=new ScopedTargetAction(true,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.DRAW,()->ScopedTargetDispatch.beforeUseReplacement(g.player)));
      ok(g.unknown&&g.budget.local(Effect.DRAW)==0&&g.budget.packets(Effect.DRAW)==0);}
   {var g=new ScopedTargetAction(true,true);denied(()->ScopedTargetDispatch.run(g.action,Effect.SHIELD_USE,()->ScopedTargetDispatch.beforeUseReplacement(g.player)));
      ok(g.unknown&&g.budget.local(Effect.SHIELD_USE)==0&&g.budget.packets(Effect.SHIELD_USE)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);release(g,()->{});ok(g.budget.local(Effect.BOW_RELEASE)==1&&g.budget.packets(Effect.BOW_RELEASE)==1&&!g.unknown);denied(()->release(g,()->{}));}
   {var g=new ScopedTargetAction(true,false);draw(g);denied(()->release(g,()->ClientActions.owner=null));ok(g.unknown&&g.budget.packets(Effect.BOW_RELEASE)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);ClientActions.cleanup=g;
    ScopedTargetDispatch.cleanup(g.action,Effect.ABORT,()->{ScopedTargetDispatch.beforeStopUsing(g.player);ScopedTargetDispatch.beforeStopMutation(g.player);g.player.using=false;});
    ok(g.budget.local(Effect.ABORT)==1&&g.budget.packets(Effect.BOW_RELEASE)==0);denied(()->ScopedTargetDispatch.cleanup(g.action,Effect.ABORT,()->{}));}
   {var g=new ScopedTargetAction(true,false);draw(g);ClientActions.cleanup=g;
    denied(()->ScopedTargetDispatch.cleanup(g.action,Effect.ABORT,()->{ScopedTargetDispatch.beforeStopUsing(g.player);ClientActions.owner=new ScopedTargetAction(false,false);ScopedTargetDispatch.beforeStopMutation(g.player);}));ok(g.unknown&&g.budget.local(Effect.ABORT)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);ClientActions.cleanup=g;
    denied(()->ScopedTargetDispatch.cleanup(g.action,Effect.ABORT,()->{ScopedTargetDispatch.beforeStopUsing(g.player);
      g.player.stack=new net.minecraft.world.item.ItemStack();g.player.stack.item=Items.BOW;
      ScopedTargetDispatch.beforeStopMutation(g.player);}));ok(g.unknown&&g.budget.local(Effect.ABORT)==0);}
   {var g=new ScopedTargetAction(true,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.DRAW,()->{ScopedTargetDispatch.beforeUse(g.player,InteractionHand.MAIN_HAND,false,true);var p=new ServerboundUseItemPacket();p.yaw=1;ScopedTargetDispatch.packet(p);}));ok(g.unknown&&g.budget.packets(Effect.DRAW)==0);}
   {var g=new ScopedTargetAction(true,false);ok(!ScopedTargetDispatch.beforeUse(g.player,InteractionHand.MAIN_HAND,false,false));denied(()->ScopedTargetDispatch.beforeRelease(g.player,false));denied(()->ScopedTargetDispatch.packet(new ServerboundUseItemPacket()));}
   {var g=new ScopedTargetAction(true,false);denied(()->ScopedTargetDispatch.packet(new ServerboundSetCarriedItemPacket()));
      denied(()->ScopedTargetDispatch.send(new ServerboundSetCarriedItemPacket()));
      denied(()->ScopedTargetDispatch.packet(new ServerboundPlayerActionPacket(){public Action getAction(){throw new AssertionError("unknown packet reader invoked");}}));}
   {var g=new ScopedTargetAction(true,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.DRAW,()->{
     ScopedTargetDispatch.beforeUse(g.player,InteractionHand.MAIN_HAND,false,true);ClientActions.owner=null;
     ScopedTargetDispatch.beforeStartUseMutation(g.player,InteractionHand.MAIN_HAND,g.player.stack,72000);}));ok(g.budget.local(Effect.DRAW)==0);}
   {var g=new ScopedTargetAction(true,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.DRAW,()->ScopedTargetDispatch.beforeStartUseMutation(g.player,InteractionHand.MAIN_HAND,g.player.stack,1)));ok(g.budget.local(Effect.DRAW)==0);}
   {var g=new ScopedTargetAction(true,false);draw(g);denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{
     ScopedTargetDispatch.beforeRelease(g.player,true);ClientActions.owner=null;
     ScopedTargetDispatch.beforeBowDraw(g.player.stack,g.player.getProjectile(g.player.stack),g.player);}));ok(g.budget.local(Effect.BOW_RELEASE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->ScopedTargetDispatch.beforeMeleeSweep(g.player,true)));ok(g.budget.local(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->ScopedTargetDispatch.beforeMeleeSecondaryMutation(g.player)));ok(g.budget.local(Effect.MELEE)==0);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
     ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ClientActions.owner=null;
     var source=new net.minecraft.world.damagesource.DamageSource();source.entity=g.player;
     ScopedTargetDispatch.beforeMeleeInvulnerability(g.target,source);}));ok(g.unknown);}
   {var g=new ScopedTargetAction(false,false);denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
     ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ClientActions.owner=null;ScopedTargetDispatch.beforeMeleePostMutation(g.player);}));ok(g.unknown);}
   {var g=new ScopedTargetAction(false,false);g.head=new net.minecraft.world.entity.Entity();g.head.id=19;
     ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{var p=new ServerboundInteractPacket();p.id=19;
       ScopedTargetDispatch.beforeAttack(g.player,g.head,false);ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);ScopedTargetDispatch.beforeMeleeImpact(g.player,g.head);});
     ok(g.budget.local(Effect.MELEE)==1&&g.budget.packets(Effect.MELEE)==1);}
   {var g=new ScopedTargetAction(false,false);g.head=new net.minecraft.world.entity.Entity();g.head.id=19;
     denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{var p=new ServerboundInteractPacket();p.id=9;ScopedTargetDispatch.packet(p);}));ok(g.budget.packets(Effect.MELEE)==0);}
   {var b=new TargetActionEffectBudget(true,true);b.reserve(Effect.SHIELD_USE);b.chargeLocal(Effect.SHIELD_USE);b.chargePacket(Effect.SHIELD_USE);b.reserve(Effect.SHIELD_RELEASE);b.chargeLocal(Effect.SHIELD_RELEASE);b.chargePacket(Effect.SHIELD_RELEASE);b.reserve(Effect.SHIELD_USE);b.chargeLocal(Effect.SHIELD_USE);b.chargePacket(Effect.SHIELD_USE);b.reserve(Effect.SHIELD_RELEASE);b.chargeLocal(Effect.SHIELD_RELEASE);b.chargePacket(Effect.SHIELD_RELEASE);denied(()->b.reserve(Effect.SHIELD_USE));}
   System.out.println("ScopedTargetHookChecks: "+checks+" production dispatch hook checks passed (test doubles; no game/mixin load)");
 }
}'''

def main():
    home=os.environ.get('JAVA_HOME')
    javac=str(Path(home)/'bin/javac') if home else shutil.which('javac')
    java=str(Path(home)/'bin/java') if home else shutil.which('java')
    if not javac or not java:raise SystemExit('JDK21 javac/java are required; no check was run')
    with tempfile.TemporaryDirectory(prefix='mdc-target-dispatch-') as d:
        root=Path(d);src=root/'src';classes=root/'classes';classes.mkdir()
        for rel,content in STUBS.items():
            p=src/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        for name in ('ScopedTargetDispatch.java','TargetActionEffectBudget.java','TargetActionReaderPolicy.java','CombatCallbackFence.java'):
            p=src/PKG/name;p.write_bytes((ROOT/'src/main/java'/PKG/name).read_bytes())
        (src/PKG/'ScopedTargetHookChecks.java').write_text(CHECKS)
        subprocess.run([javac,'-J-Xmx256m','-proc:none','--release','21','-d',str(classes),*map(str,src.rglob('*.java'))],check=True)
        subprocess.run([java,'-Xmx256m','-cp',str(classes),'io.github.campione01.mineclientbridge.ScopedTargetHookChecks'],check=True)
if __name__=='__main__':main()
