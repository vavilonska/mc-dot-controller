package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundContainerClickPacket;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.item.ItemStack;

/** Recovery-only dynamic token; vanilla owns all real stack mutations and packet delivery. */
public final class InventoryRecoveryDispatch {
    private static boolean clickInstalled, sendInstalled;
    private static final ThreadLocal<Token> CALL = new ThreadLocal<>();
    public static void clickInstalled() { clickInstalled = true; }
    public static void sendInstalled() { sendInstalled = true; }
    static boolean ready() { return clickInstalled && sendInstalled; }
    public static void beforeClick() { Token token = CALL.get(); if (token != null) token.beforeClick(); }
    public static void beforeSend(Packet<?> packet) { Token token = CALL.get(); if (token != null) token.beforeSend(packet); }
    static Runnable run(Minecraft mc, ClientActionRequest request, BooleanSupplier owner, Runnable policy, Runnable freshness, Runnable vanilla) {
        need(ready() && CALL.get() == null, "inventory_recovery_native_fence_unavailable");
        Token token = new Token(mc, request, owner, policy, freshness);
        CALL.set(token);
        try { vanilla.run(); token.after(); return token::after; }
        finally { CALL.remove(); }
    }
    private static final class Token {
        final Minecraft mc; final ClientActionRequest request; final BooleanSupplier owner; final Runnable policy, freshness;
        final AbstractContainerMenu menu; final Object player, level, gameMode, inventory;
        final JsonObject context; final int state, selected, index;
        final ItemStack[] slots, items; final ItemStack cursor;
        final net.minecraft.world.inventory.Slot[] slotObjects; final boolean[] activeSlots;
        final InventoryRecoveryBoundary boundary=new InventoryRecoveryBoundary();
        Token(Minecraft mc, ClientActionRequest request, BooleanSupplier owner, Runnable policy, Runnable freshness) {
            this.mc=mc; this.request=request; this.owner=owner; this.policy=policy; this.freshness=freshness;
            player=mc.player; level=mc.level; gameMode=mc.gameMode; inventory=mc.player.getInventory();
            menu=mc.player.containerMenu; state=menu.getStateId(); selected=mc.player.getInventory().selected;
            context=InventoryRecoveryGuard.context(menu); index=menu.slots.get(request.slot()).getContainerSlot();
            slots=new ItemStack[menu.slots.size()]; items=new ItemStack[41];
            slotObjects=new net.minecraft.world.inventory.Slot[slots.length]; activeSlots=new boolean[slots.length];
            for(int i=0;i<slots.length;i++){slotObjects[i]=menu.slots.get(i);activeSlots[i]=slotObjects[i].isActive();slots[i]=slotObjects[i].getItem().copy();}
            for(int i=0;i<41;i++)items[i]=mc.player.getInventory().getItem(i).copy();
            ItemStack carried=menu.getCarried().copy(), target=slots[request.slot()];
            if(request.original().getAsJsonObject("inventory_recovery").get("phase").getAsString().equals("pickup_hand")) {
                cursor=target.copy(); slots[request.slot()]=ItemStack.EMPTY; items[index]=ItemStack.EMPTY;
            } else {
                int amount=Math.min(carried.getCount(),Math.min(64,menu.slots.get(request.slot()).getMaxStackSize(carried))-target.getCount());
                need(amount>0,"inventory_recovery_destination_full");
                ItemStack after=carried.copyWithCount(target.getCount()+amount);
                slots[request.slot()]=after; items[index]=after;
                cursor=carried.copyWithCount(carried.getCount()-amount);
            }
            exactOwner();
            need(InventoryRecoveryGuard.check(mc,request)==null,"inventory_recovery_pre_copy_changed");
            exactOwner();
        }
        void exactOwner() {
            need(owner.getAsBoolean() && mc.player==player && mc.level==level && mc.gameMode==gameMode
                && mc.player.getInventory()==inventory && mc.player.containerMenu==menu
                && menu.getStateId()==state && mc.player.getInventory().selected==selected
                && context.equals(InventoryRecoveryGuard.context(menu)),"inventory_recovery_owner_changed");
        }
        void beforeClick() {
            boundary.click(() -> {
                exactOwner(); policy.run();
                need(InventoryRecoveryGuard.check(mc,request)==null,"inventory_recovery_pre_click_changed");
                exactOwner(); freshness.run(); exactOwner();
            });
        }
        void postState() {
            exactOwner(); policy.run(); exactOwner();
            need(menu.slots.size()==slots.length && mc.player.getInventory().getContainerSize()==41
                && ItemStack.matches(menu.getCarried(),cursor),"inventory_recovery_post_cursor_changed");
            for(int i=0;i<slots.length;i++)need(menu.slots.get(i)==slotObjects[i] && slotObjects[i].index==i
                && slotObjects[i].isActive()==activeSlots[i] && ItemStack.matches(slotObjects[i].getItem(),slots[i]),"inventory_recovery_post_slot_changed");
            for(int i=0;i<41;i++)need(ItemStack.matches(mc.player.getInventory().getItem(i),items[i]),"inventory_recovery_post_inventory_changed");
            exactOwner();
        }
        void beforeSend(Packet<?> packet) {
            boundary.send(() -> {
            need(packet instanceof ServerboundContainerClickPacket,"inventory_recovery_unexpected_packet");
            postState(); var click=(ServerboundContainerClickPacket)packet;
            need(click.getContainerId()==menu.containerId && click.getStateId()==state && click.getSlotNum()==request.slot()
                && click.getButtonNum()==0 && click.getClickType()==ClickType.PICKUP && ItemStack.matches(click.getCarriedItem(),cursor)
                && click.getChangedSlots().size()==1 && click.getChangedSlots().containsKey(request.slot())
                && ItemStack.matches(click.getChangedSlots().get(request.slot()),slots[request.slot()]),"inventory_recovery_packet_changed");
            exactOwner(); freshness.run(); exactOwner();
            });
        }
        void after() { boundary.after(this::postState); }
    }
    private static void need(boolean condition,String reason) { if(!condition)throw new ClientActionRequest.Rejected(409,reason); }
    private InventoryRecoveryDispatch() {}
}
