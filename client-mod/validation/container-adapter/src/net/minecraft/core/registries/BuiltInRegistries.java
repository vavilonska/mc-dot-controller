package net.minecraft.core.registries;
import net.minecraft.world.item.Item;
public final class BuiltInRegistries {
 public static final Registry ITEM=new Registry();
 public static final class Registry {public String getKey(Item item){return item.id;}}
}
