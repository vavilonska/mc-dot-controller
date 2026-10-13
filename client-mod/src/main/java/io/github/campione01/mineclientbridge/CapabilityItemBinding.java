package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.UUID;
import net.minecraft.world.item.ItemStack;

/** Bounded, process-local observation handles, not credentials or inventory mutation. */
final class CapabilityItemBinding {
    private static final int LIMIT=4096;
    private static final LinkedHashMap<String,ItemStack> ITEMS=new LinkedHashMap<>();
    static void append(ItemStack item, JsonObject out) {
        ItemStack value=item==null?ItemStack.EMPTY:item;
        String id=null,components=null;
        for(var entry:ITEMS.entrySet()) {
            if(ItemStack.isSameItemSameComponents(entry.getValue(),value)) {
                if(components==null)components=entry.getKey();
                if(entry.getValue().getCount()==value.getCount()){id=entry.getKey();break;}
            }
        }
        if(id==null){id=UUID.randomUUID().toString();ITEMS.put(id,value.copy());}
        if(components==null)components=id;
        while(ITEMS.size()>LIMIT) ITEMS.remove(ITEMS.keySet().iterator().next());
        out.addProperty("item_fingerprint",id);
        out.addProperty("component_fingerprint",components);
        out.addProperty("max_stack_size",item==null || item.isEmpty()?0:item.getMaxStackSize());
    }
    static boolean matches(JsonObject expected,ItemStack actual) {
        if(expected==null || !expected.has("item_fingerprint")) return false;
        ItemStack captured=ITEMS.get(ClientActionRequest.string(expected,"item_fingerprint"));
        return captured!=null && same(captured,actual);
    }
    static boolean same(ItemStack a,ItemStack b) {
        return a.getCount()==b.getCount() && ItemStack.isSameItemSameComponents(a,b);
    }
    private CapabilityItemBinding() { }
}
