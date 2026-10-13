package net.minecraft.world.item;
import java.util.*;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.component.DataComponents.Key;
public final class ItemStack {
 public static final ItemStack EMPTY=new ItemStack(new Item("minecraft:air"),0,0);
 private final Item item; private final int count,maxDamage;
 private final Map<Key<?>,Optional<?>> patch=new LinkedHashMap<>();
 public ItemStack(Item item,int count,int maxDamage){this.item=item;this.count=count;this.maxDamage=maxDamage;}
 public Item getItem(){return item;} public int getCount(){return count;}
 public boolean isEmpty(){return count<=0;} public int getMaxDamage(){return maxDamage;}
 public int getDamageValue(){Integer n=get(DataComponents.DAMAGE);return n==null?0:n;}
 @SuppressWarnings("unchecked") public <T>T get(Key<T> key){return (T)patch.getOrDefault(key,Optional.empty()).orElse(null);}
 public <T>T getOrDefault(Key<T> key,T fallback){T v=get(key);return v==null?fallback:v;}
 public <T>ItemStack set(Key<T> key,T value){patch.put(key,Optional.of(value));return this;}
 public ItemStack remove(Key<?> key){patch.put(key,Optional.empty());return this;}
 public Map<Key<?>,Optional<?>> getComponentsPatch(){return patch;}
 public boolean isComponentsPatchEmpty(){return patch.isEmpty();}
}
