package io.github.campione01.mineclientbridge;
import net.minecraft.core.component.DataComponentMap;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.component.DataComponentPatch;
import net.minecraft.core.component.PatchedDataComponentMap;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
/** Immutable vanilla component container + identity values; no component equality callbacks. */
final class TypedPortalStack {
    private static final Object REMOVED=new Object();
    private final Item item;
    private final int count;
    private final Object prototype;
    private final IdentityComponentSnapshot defaults=new IdentityComponentSnapshot(),patch=new IdentityComponentSnapshot();
    TypedPortalStack(ItemStack stack){
        TypedPortalReaderPolicy.exact(stack,ItemStack.class);item=stack.getItem();count=stack.getCount();
        if(stack.isEmpty()){prototype=DataComponentMap.EMPTY;return;}
        try{if(item.getClass().getMethod("components").getDeclaringClass()!=Item.class)throw new IllegalStateException("typed_component_prototype_reader_unknown");}
        catch(ReflectiveOperationException failure){throw new IllegalStateException("typed_component_prototype_reader_unknown",failure);}
        var base=stack.getPrototype();prototype=base;
        if(base!=DataComponentMap.EMPTY&&!(base.getClass().getClassLoader()==DataComponentMap.class.getClassLoader()
            &&base.getClass().getName().equals("net.minecraft.core.component.DataComponentMap$Builder$SimpleMap")))
            throw new IllegalStateException("typed_component_prototype_container_unknown");
        TypedPortalReaderPolicy.exact(stack.getComponents(),PatchedDataComponentMap.class);
        for(var value:base)defaults.add(value.type(),value.value());
        DataComponentPatch changes=TypedPortalReaderPolicy.exact(stack.getComponentsPatch(),DataComponentPatch.class);
        for(var row:changes.entrySet())patch.add(row.getKey(),row.getValue().isPresent()?row.getValue().get():REMOVED);
    }
    boolean same(ItemStack stack){return same(new TypedPortalStack(stack),false,false);}
    boolean same(ItemStack stack,boolean allowCount,boolean allowDamage){return same(new TypedPortalStack(stack),allowCount,allowDamage);}
    private boolean same(TypedPortalStack now,boolean allowCount,boolean allowDamage){
        return item==now.item&&(allowCount||count==now.count)&&prototype==now.prototype&&defaults.same(now.defaults,null)
            &&patch.same(now.patch,allowDamage?DataComponents.DAMAGE:null);
    }
}
