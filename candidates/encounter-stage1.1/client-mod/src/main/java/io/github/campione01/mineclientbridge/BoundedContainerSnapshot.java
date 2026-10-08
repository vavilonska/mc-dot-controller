package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemContainerContents;
import net.minecraft.world.level.block.ShulkerBoxBlock;

/** Client-thread-only, bounded observation. No arbitrary NBT, recursion, or opaque value serialization. */
final class BoundedContainerSnapshot {
    private static int remainingBoxes=4;
    static void beginSnapshot() { remainingBoxes=4; }
    static void append(ItemStack stack, JsonObject item) {
        boolean complete=true;
        var name=stack.get(DataComponents.CUSTOM_NAME);
        if (name!=null) {
            String text=name.getString(129);
            item.addProperty("custom_name",text.substring(0,Math.min(128,text.length())));
            item.addProperty("custom_name_truncated",text.length()>128);
            // Plain text is useful to a human, but cannot identify styled names exactly.
            complete=false;
        }
        boolean box=isBox(stack);
        int omitted=0;
        for (var entry:stack.getComponentsPatch().entrySet()) {
            var type=entry.getKey();
            // Removing a prototype component (even damage=0) changes semantics;
            // the basic value fields do not encode component presence.
            if (entry.getValue().isEmpty() || (type!=DataComponents.DAMAGE && type!=DataComponents.CUSTOM_NAME
                    && !(box && type==DataComponents.CONTAINER))) omitted++;
        }
        if (omitted>0) complete=false;
        item.addProperty("unrepresented_component_changes",omitted);
        if (box) {
            JsonObject container=new JsonObject();
            container.addProperty("schema_version",1);
            container.addProperty("capacity",27);
            container.addProperty("nested_containers_supported",false);
            var contents=stack.getOrDefault(DataComponents.CONTAINER,ItemContainerContents.EMPTY);
            int total=contents.getSlots();
            boolean truncated=total>27 || remainingBoxes<=0;
            JsonArray slots=new JsonArray();
            if (remainingBoxes>0) {
                remainingBoxes--;
                for (int i=0;i<Math.min(total,27);i++) {
                    ItemStack child=contents.getStackInSlot(i);
                    if (child.isEmpty()) continue;
                    JsonObject row=new JsonObject(); row.addProperty("slot",i);
                    row.addProperty("id",BuiltInRegistries.ITEM.getKey(child.getItem()).toString());
                    row.addProperty("count",child.getCount()); row.addProperty("damage",child.getDamageValue());
                    // Component-bearing contents remain visible by basic identity,
                    // but must never be accepted as exact verified cargo.
                    boolean exact=child.isComponentsPatchEmpty() && !isBox(child);
                    row.addProperty("identity_complete",exact);
                    if (!exact) complete=false;
                    slots.add(row);
                }
            }
            if (truncated) complete=false;
            container.addProperty("slots_truncated",truncated);
            container.addProperty("slot_extent",total);
            container.add("items",slots);
            item.add("container",container);
        }
        item.addProperty("identity_complete",complete);
    }
    private static boolean isBox(ItemStack stack) {
        return stack.getItem() instanceof BlockItem block && block.getBlock() instanceof ShulkerBoxBlock;
    }
    private BoundedContainerSnapshot() { }
}
