package net.minecraft.core.component;
import net.minecraft.world.item.component.ItemContainerContents;
public final class DataComponents {
 public static final class Key<T> {}
 public record Text(String value) { public String getString(int limit) {return value.substring(0, Math.min(limit,value.length()));} }
 public static final Key<Integer> DAMAGE=new Key<>();
 public static final Key<Text> CUSTOM_NAME=new Key<>();
 public static final Key<ItemContainerContents> CONTAINER=new Key<>();
 public static final Key<String> OTHER=new Key<>();
}
