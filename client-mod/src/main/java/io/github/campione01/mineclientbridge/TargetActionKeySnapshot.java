package io.github.campione01.mineclientbridge;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.function.BooleanSupplier;
import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Options;
import net.minecraft.client.ToggleKeyMapping;
import net.neoforged.neoforge.client.settings.IKeyConflictContext;
import net.neoforged.neoforge.client.settings.KeyModifier;

/** Pure key-state witness. Never evaluates conflict contexts, modifiers or toggle suppliers.
 * Exact vanilla shift/sprint roles use ToggleKeyMapping even when toggle mode is disabled.
 * This reader observes only; it never changes key state, bindings or toggle options. */
final class TargetActionKeySnapshot {
    private static final Field DOWN=field(KeyMapping.class,"isDown",boolean.class,false);
    private static final Field CLICKS=field(KeyMapping.class,"clickCount",int.class,false);
    private static final Field NAME=field(KeyMapping.class,"name",String.class,true);
    private static final Field CATEGORY=field(KeyMapping.class,"category",String.class,true);
    private static final Field KEY=field(KeyMapping.class,"key",InputConstants.Key.class,false);
    private static final Field DEFAULT_KEY=field(KeyMapping.class,"defaultKey",InputConstants.Key.class,true);
    private static final Field MODIFIER=field(KeyMapping.class,"keyModifier",KeyModifier.class,false);
    private static final Field DEFAULT_MODIFIER=field(KeyMapping.class,"keyModifierDefault",KeyModifier.class,false);
    private static final Field CONTEXT=field(KeyMapping.class,"keyConflictContext",IKeyConflictContext.class,false);
    private static final Field TOGGLE=field(ToggleKeyMapping.class,"needsToggle",BooleanSupplier.class,true);
    private static Field field(Class<?> owner,String name,Class<?> type,boolean isFinal){
        try{
            var field=owner.getDeclaredField(name);int flags=field.getModifiers();
            if(field.getDeclaringClass()!=owner||field.getType()!=type||Modifier.isStatic(flags)
                ||Modifier.isFinal(flags)!=isFinal||!field.trySetAccessible())return null;
            return field;
        }catch(ReflectiveOperationException|SecurityException unavailable){return null;}
    }
    static boolean ready(){return DOWN!=null&&CLICKS!=null&&NAME!=null&&CATEGORY!=null&&KEY!=null
        &&DEFAULT_KEY!=null&&MODIFIER!=null&&DEFAULT_MODIFIER!=null&&CONTEXT!=null&&TOGGLE!=null;}
    static void append(Options options,List<Object> identities,List<Long> values){
        require(options!=null&&options.getClass()==Options.class,"target_scope_options_reader_unknown");
        identities.add(options);
        append(options.keyMappings,options.keyUse,options.keyShift,options.keySprint,identities,values);
        appendRoles(options.keyMappings,new KeyMapping[]{options.keyUp,options.keyLeft,options.keyDown,options.keyRight,
            options.keyJump,options.keyShift,options.keySprint,options.keyInventory,options.keySwapOffhand,options.keyDrop,
            options.keyUse,options.keyAttack,options.keyPickItem,options.keyChat,options.keyPlayerList,options.keyCommand,
            options.keySocialInteractions,options.keyScreenshot,options.keyTogglePerspective,options.keySmoothCamera,
            options.keyFullscreen,options.keySpectatorOutlines,options.keyAdvancements,
            options.keySaveHotbarActivator,options.keyLoadHotbarActivator},options.keyHotbarSlots,identities);
    }
    /** Every ordinary Options role is bound, including roles not directly used by this action. */
    static void appendRoles(KeyMapping[] mappings,KeyMapping[] roles,KeyMapping[] hotbar,List<Object> identities){
        require(mappings!=null&&roles!=null&&roles.length==25&&hotbar!=null&&hotbar.length==9,"target_scope_key_role_coverage");
        var members=new IdentityHashMap<KeyMapping,Boolean>();for(var key:mappings)members.put(key,Boolean.TRUE);
        var seen=new IdentityHashMap<KeyMapping,Boolean>();
        for(var key:roles){require(key!=null&&members.containsKey(key)&&seen.put(key,Boolean.TRUE)==null,"target_scope_key_role_member_changed");identities.add(key);}
        identities.add(hotbar);
        for(var key:hotbar){require(key!=null&&members.containsKey(key)&&seen.put(key,Boolean.TRUE)==null,"target_scope_key_role_member_changed");identities.add(key);}
    }
    /** Neutral typed lanes bind clicks but refuse any latched raw key without evaluating its context. */
    static void appendNeutral(Options options,List<Object> identities,List<Long> values){
        int start=values.size();append(options,identities,values);
        requireDown(values,start,options.keyMappings,options.keyUse,false);
    }
    static void appendNeutral(KeyMapping[] mappings,KeyMapping use,KeyMapping shift,KeyMapping sprint,
            List<Object> identities,List<Long> values){
        int start=values.size();append(mappings,use,shift,sprint,identities,values);
        requireDown(values,start,mappings,use,false);
    }
    /** An activated target owner can own use during a draw; no movement latch is admitted. */
    static void appendStationary(Options options,boolean allowUse,List<Object> identities,List<Long> values){
        int start=values.size();append(options,identities,values);
        requireDown(values,start,options.keyMappings,options.keyUse,allowUse);
    }
    static void appendStationary(KeyMapping[] mappings,KeyMapping use,KeyMapping shift,KeyMapping sprint,
            boolean allowUse,List<Object> identities,List<Long> values){
        int start=values.size();append(mappings,use,shift,sprint,identities,values);
        requireDown(values,start,mappings,use,allowUse);
    }
    private static void requireDown(List<Long> values,int start,KeyMapping[] mappings,KeyMapping use,boolean allowUse){
        for(int i=0;i<mappings.length;i++)
            require(values.get(start+2*i)==0L||allowUse&&mappings[i]==use,"target_scope_nonowned_key_held");
    }
    /** Parameter seam permits official key instances without constructing a game. */
    static void append(KeyMapping[] mappings,KeyMapping use,KeyMapping shift,KeyMapping sprint,
            List<Object> identities,List<Long> values){
        require(ready(),"target_scope_key_fields_unavailable");
        require(mappings!=null&&mappings.length>=3&&mappings.length<=512,"target_scope_key_coverage");
        require(use!=null&&use.getClass()==KeyMapping.class&&shift!=null&&shift.getClass()==ToggleKeyMapping.class
            &&sprint!=null&&sprint.getClass()==ToggleKeyMapping.class&&shift!=sprint,"target_scope_key_role_unknown");
        identities.add(mappings);identities.add(use);identities.add(shift);identities.add(sprint);
        var seen=new IdentityHashMap<KeyMapping,Boolean>();
        for(KeyMapping key:mappings){
            require(key!=null&&seen.put(key,Boolean.TRUE)==null,"target_scope_key_coverage");
            boolean toggle=key==shift||key==sprint;
            require(key.getClass()==(toggle?ToggleKeyMapping.class:KeyMapping.class),"target_scope_key_reader_unknown");
            try{
                identities.add(key);identities.add(NAME.get(key));identities.add(CATEGORY.get(key));
                identities.add(KEY.get(key));identities.add(DEFAULT_KEY.get(key));
                identities.add(MODIFIER.get(key));identities.add(DEFAULT_MODIFIER.get(key));identities.add(CONTEXT.get(key));
                if(toggle)identities.add(TOGGLE.get(key));
                values.add(DOWN.getBoolean(key)?1L:0L);values.add((long)CLICKS.getInt(key));
            }catch(IllegalAccessException|IllegalArgumentException unavailable){
                throw new ClientActionRequest.Rejected(409,"target_scope_key_fields_unavailable");
            }
        }
        require(seen.containsKey(use)&&seen.containsKey(shift)&&seen.containsKey(sprint),"target_scope_key_roles_missing");
    }
    private static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    private TargetActionKeySnapshot(){}
}
