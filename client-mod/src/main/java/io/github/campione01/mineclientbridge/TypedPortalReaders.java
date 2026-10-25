package io.github.campione01.mineclientbridge;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.multiplayer.ClientChunkCache;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.world.entity.ai.attributes.AttributeMap;
import net.minecraft.world.entity.ai.attributes.AttributeInstance;
import net.minecraft.world.entity.ai.attributes.Attribute;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.ai.attributes.RangedAttribute;
import net.neoforged.neoforge.common.PercentageAttribute;
import net.minecraft.world.entity.player.Abilities;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.food.FoodData;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
/** Audited vanilla data readers, separated from shape/ray/entity-enumeration callbacks. */
final class TypedPortalReaders {
    private static final java.lang.reflect.Field CONTEXT_HIT=contextHitField();
    private static java.lang.reflect.Field contextHitField(){
        try{
            var field=net.minecraft.world.item.context.UseOnContext.class.getDeclaredField("hitResult");
            if(field.getType()!=net.minecraft.world.phys.BlockHitResult.class||java.lang.reflect.Modifier.isStatic(field.getModifiers())
                ||!java.lang.reflect.Modifier.isFinal(field.getModifiers())||!field.trySetAccessible())return null;
            return field;
        }catch(ReflectiveOperationException|RuntimeException unavailable){return null;}
    }
    static void itemContextReaderReady(){require(CONTEXT_HIT!=null,"typed_item_context_raw_reader_unavailable");}
    static net.minecraft.world.phys.BlockHitResult contextHit(net.minecraft.world.item.context.UseOnContext context){
        exact(context,net.minecraft.world.item.context.UseOnContext.class);
        itemContextReaderReady();
        try{return exact((net.minecraft.world.phys.BlockHitResult)CONTEXT_HIT.get(context),net.minecraft.world.phys.BlockHitResult.class);}
        catch(IllegalAccessException unavailable){throw new IllegalStateException("typed_item_context_raw_reader_unavailable",unavailable);}
    }

    private final Minecraft minecraft;
    private final LocalPlayer player;
    private final ClientLevel level;
    private final MultiPlayerGameMode mode;
    private final Inventory inventory;
    private final InventoryMenu menu;
    private final FoodData food;
    private final Abilities abilities;
    private final SynchedEntityData entityData;
    private final AttributeMap attributes;
    private final net.minecraft.core.Holder<Attribute> movementHolder,gravityHolder,reachHolder;
    private final Attribute movementValue,gravityValue,reachValue;
    private final AttributeInstance movement,gravity,reach;
    private final ClientChunkCache chunks;
    private final ClientLevel.ClientLevelData data;
    TypedPortalReaders(Minecraft mc){
        minecraft=exact(mc,Minecraft.class);player=exact(mc.player,LocalPlayer.class);level=exact(mc.level,ClientLevel.class);mode=exact(mc.gameMode,MultiPlayerGameMode.class);
        inventory=exact(player.getInventory(),Inventory.class);menu=exact(player.inventoryMenu,InventoryMenu.class);
        food=exact(player.getFoodData(),FoodData.class);abilities=exact(player.getAbilities(),Abilities.class);entityData=exact(player.getEntityData(),SynchedEntityData.class);
        attributes=exact(player.getAttributes(),AttributeMap.class);
        movementHolder=exact(Attributes.MOVEMENT_SPEED,net.minecraft.core.Holder.Reference.class);
        gravityHolder=exact(Attributes.GRAVITY,net.minecraft.core.Holder.Reference.class);
        reachHolder=exact(Attributes.BLOCK_INTERACTION_RANGE,net.minecraft.core.Holder.Reference.class);
        // Lazy AttributeInstance construction reads the holder value's default.
        // Admit those exact readers before asking the AttributeMap for instances.
        movementValue=movementHolder.value();gravityValue=gravityHolder.value();reachValue=reachHolder.value();
        attributeReaders(movementValue,gravityValue,reachValue);
        movement=exact(player.getAttribute(movementHolder),AttributeInstance.class);gravity=exact(player.getAttribute(gravityHolder),AttributeInstance.class);
        reach=exact(player.getAttribute(reachHolder),AttributeInstance.class);
        chunks=exact(level.getChunkSource(),ClientChunkCache.class);data=exact(level.getLevelData(),ClientLevel.ClientLevelData.class);
        current(mc);
    }
    // Exact official holder-specific classes: NeoForge replaces movement speed's
    // value with PercentageAttribute, which inherits the audited numeric readers.
    // Gravity/reach remain exact RangedAttribute. Never admit arbitrary subclasses.
    static void attributeReaders(Object movementSpeed,Object gravity,Object reach){
        exact(movementSpeed,PercentageAttribute.class);exact(gravity,RangedAttribute.class);exact(reach,RangedAttribute.class);
    }
    private void attributeDefinitionsCurrent(){
        require(Attributes.MOVEMENT_SPEED==movementHolder&&Attributes.GRAVITY==gravityHolder&&Attributes.BLOCK_INTERACTION_RANGE==reachHolder
            &&movementHolder.value()==movementValue&&gravityHolder.value()==gravityValue&&reachHolder.value()==reachValue,
            "typed_portal_attribute_definition_changed");
    }
    void current(Minecraft mc){
        require(mc==minecraft&&mc.player==player&&mc.level==level&&mc.gameMode==mode,"typed_portal_reader_context_changed");
        attributeDefinitionsCurrent();
        require(player.getInventory()==inventory&&player.inventoryMenu==menu&&player.containerMenu==menu
            &&player.getFoodData()==food&&player.getAbilities()==abilities&&player.getEntityData()==entityData&&player.getAttributes()==attributes
            &&player.getAttribute(Attributes.MOVEMENT_SPEED)==movement&&player.getAttribute(Attributes.GRAVITY)==gravity&&player.getAttribute(Attributes.BLOCK_INTERACTION_RANGE)==reach
            &&level.getChunkSource()==chunks&&level.getLevelData()==data,"typed_portal_reader_identity_changed");
        exact(player.getDeltaMovement(),Vec3.class);exact(player.position(),Vec3.class);exact(player.getBoundingBox(),AABB.class);
        exact(player.getActiveEffectsMap(),java.util.HashMap.class);
        require(movement.getAttribute()==Attributes.MOVEMENT_SPEED&&gravity.getAttribute()==Attributes.GRAVITY&&reach.getAttribute()==Attributes.BLOCK_INTERACTION_RANGE
            &&Double.isFinite(movement.getBaseValue())&&movement.getBaseValue()>=0&&movement.getBaseValue()<=.10000001&&movement.getModifiers().isEmpty()
            &&Math.abs(gravity.getBaseValue()-.08)<=1e-9&&gravity.getModifiers().isEmpty()
            &&Double.isFinite(reach.getBaseValue())&&reach.getBaseValue()>0&&reach.getBaseValue()<=6&&reach.getModifiers().isEmpty(),"typed_portal_attribute_reader_changed");
        exact(inventory.items,net.minecraft.core.NonNullList.class);exact(inventory.armor,net.minecraft.core.NonNullList.class);exact(inventory.offhand,net.minecraft.core.NonNullList.class);
        for(int i=0;i<41;i++)exact(inventory.getItem(i),ItemStack.class);
        exact(menu.getCarried(),ItemStack.class);
    }
    void warmEffectiveValues(){
        // Exact instance/definition readers and empty modifiers were admitted by current().
        // Populate lazy caches before their raw fields become a callback boundary.
        require(movement.getValue()==movement.getBaseValue()&&gravity.getValue()==gravity.getBaseValue()
            &&reach.getValue()==reach.getBaseValue(),"typed_portal_effective_attribute_changed");
    }
    void appendEffectiveValues(java.util.List<Object> identities,java.util.List<Long> values){
        TypedPortalPolicyBoundary.appendAttribute(movement,identities,values);
        TypedPortalPolicyBoundary.appendAttribute(gravity,identities,values);
        TypedPortalPolicyBoundary.appendAttribute(reach,identities,values);
    }
    boolean originalHealthAtLeast(float floor){
        require(player.getEntityData()==entityData,"typed_portal_original_health_reader_changed");
        return PortalContactPolicy.originalHealth(player.isDeadOrDying(),player.getHealth(),floor);
    }
    static net.minecraft.world.level.chunk.LevelChunk chunk(ClientLevel level,net.minecraft.core.BlockPos pos){
        exact(level,ClientLevel.class);exact(level.getChunkSource(),ClientChunkCache.class);
        require(level.hasChunkAt(pos),"typed_portal_raw_chunk_unloaded");
        var chunk=exact(level.getChunkAt(pos),net.minecraft.world.level.chunk.LevelChunk.class);
        if(!level.isOutsideBuildHeight(pos)){
            var section=exact(chunk.getSection(chunk.getSectionIndex(pos.getY())),net.minecraft.world.level.chunk.LevelChunkSection.class);
            exact(section.getStates(),net.minecraft.world.level.chunk.PalettedContainer.class);
        }
        return chunk;
    }
    static net.minecraft.world.level.block.state.BlockState block(ClientLevel level,net.minecraft.core.BlockPos pos){return chunk(level,pos).getBlockState(pos);}
    static net.minecraft.world.level.block.entity.BlockEntity blockEntity(ClientLevel level,net.minecraft.core.BlockPos pos){return chunk(level,pos).getBlockEntity(pos);}
    // Vanilla BlockGetter traversal keeps an exact MutableBlockPos in its hit.
    // Accept only the two official data classes; argumentFrame binds the original
    // reference and primitive coordinates around every callback, without copying it.
    static boolean hitPositionKnown(net.minecraft.core.BlockPos pos){
        return pos!=null&&(pos.getClass()==net.minecraft.core.BlockPos.class
            ||pos.getClass()==net.minecraft.core.BlockPos.MutableBlockPos.class);
    }
    static net.minecraft.core.BlockPos hitPosition(net.minecraft.core.BlockPos pos){
        require(hitPositionKnown(pos),"typed_portal_hit_position_reader_unknown");return pos;
    }
    private static <T>T exact(T value,Class<?> expected){return TypedPortalReaderPolicy.exact(value,expected);}
    private static void require(boolean ok,String message){if(!ok)throw new IllegalStateException(message);}
}
