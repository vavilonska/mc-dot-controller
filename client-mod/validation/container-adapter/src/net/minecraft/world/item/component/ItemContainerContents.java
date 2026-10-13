package net.minecraft.world.item.component;
import java.util.List;
import net.minecraft.world.item.ItemStack;
public final class ItemContainerContents {
 public static final ItemContainerContents EMPTY=new ItemContainerContents(List.of());
 private final List<ItemStack> items;
 public ItemContainerContents(List<ItemStack> items){this.items=List.copyOf(items);}
 public int getSlots(){return items.size();}
 public ItemStack getStackInSlot(int i){return items.get(i);}
}
