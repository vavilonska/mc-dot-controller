package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.boss.EnderDragonPart;
import net.minecraft.world.entity.boss.enderdragon.EnderDragon;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;

/** Immutable native admission plus exact lifetime binding for one stationary target action. */
final class ScopedTargetAction {
    static final String PROFILE="target-action-stationary-v1";
    static final Set<String> MELEE=Set.of("minecraft:zombie","minecraft:husk","minecraft:zombie_villager",
        "minecraft:skeleton","minecraft:stray","minecraft:bogged","minecraft:spider","minecraft:shulker",
        "minecraft:enderman","minecraft:ender_dragon");
    static final Set<String> RANGED=Set.of("minecraft:zombie","minecraft:husk","minecraft:zombie_villager",
        "minecraft:skeleton","minecraft:stray","minecraft:bogged","minecraft:spider","minecraft:shulker",
        "minecraft:creeper","minecraft:cave_spider","minecraft:blaze","minecraft:end_crystal");
    final LocalPlayer player;
    final ClientLevel level;
    final Object gameMode,server,options;
    final net.minecraft.client.KeyMapping useKey;
    final Entity target;
    final JsonObject body;
    final long deadline,startNano;
    final String session,world;
    final Vec3 origin;
    final int selected;
    final boolean ranged,shield;
    final TargetActionEffectBudget budget;
    final java.util.Map<EquipmentSlot,ItemStack> equipment=new EnumMap<>(EquipmentSlot.class);
    final ItemStack ammunition;
    final CapabilityTargetAction executor;
    final List<BlockPos> station=new ArrayList<>();
    final List<BlockState> stationStates=new ArrayList<>();
    final JsonObject captured;
    final Geometry capturedGeometry;
    ActionRegistry.Entry entry;
    private long ownerRevision;
    private boolean unknown;

    ScopedTargetAction(Minecraft mc,ClientActionRequest command,long nano){
        validateIntent(command.original());
        body=command.original().deepCopy();player=mc.player;level=mc.level;gameMode=mc.gameMode;server=mc.getSingleplayerServer();
        options=mc.options;useKey=mc.options==null?null:mc.options.keyUse;
        require(useKey!=null&&useKey.getClass()==net.minecraft.client.KeyMapping.class,"target_scope_exact_use_key_required");
        require(mc.getClass()==Minecraft.class&&server!=null&&server.getClass()==net.minecraft.client.server.IntegratedServer.class
            &&player!=null&&player.getClass()==LocalPlayer.class&&level!=null&&level.getClass()==ClientLevel.class
            &&gameMode!=null&&gameMode.getClass()==net.minecraft.client.multiplayer.MultiPlayerGameMode.class,
            "target_scope_exact_context_readers_required");
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class
            &&player.inventoryMenu.getClass()==net.minecraft.world.inventory.InventoryMenu.class,"target_scope_exact_inventory_readers_required");
        session=ClientActions.session();world=WorldGeneration.current(level);origin=player.position();selected=player.getInventory().selected;
        require(finiteBounded(origin),"target_scope_origin_nonfinite_or_unbounded");
        startNano=nano;deadline=nano+command.timeoutMs()*1_000_000L;
        ranged=command.action().equals("shoot_entity");shield=body.has("blaze_safety_mode")&&body.get("blaze_safety_mode").getAsString().equals("shield_window");
        budget=new TargetActionEffectBudget(ranged,shield);
        target=level.getEntity(ClientActionRequest.integer(body,"target_entity_id",-1));
        require(target!=null,"target_scope_target_missing");
        requireEntityReaders(target);requireEntityReaders(player);requireTargetClass();requirePlayerReaders();
        for(EquipmentSlot slot:EquipmentSlot.values())equipment.put(slot,player.getItemBySlot(slot).copy());
        ammunition=ranged?player.getProjectile(player.getMainHandItem()).copy():ItemStack.EMPTY;
        require(!ranged||ammunition.is(Items.ARROW)&&ammunition.getCount()>0,"target_scope_plain_arrow_required");
        require(!player.isUsingItem()&&player.containerMenu==player.inventoryMenu&&player.containerMenu.getCarried().isEmpty(),"target_scope_admission_player_unavailable");
        captureStation(mc);
        executor=CapabilityTargetAction.start(mc,body);executor.bindScoped(this);
        capturedGeometry=geometry();captured=factsNow();
        admission(mc);admissionRawFence(mc);
    }
    CapabilityTargetAction action(){return executor;}
    static void validateIntent(JsonObject body){
        CapabilityTargetAction.validate(body);
        boolean ranged=ClientActionRequest.string(body,"action").equals("shoot_entity");
        String type=ClientActionRequest.string(body,"target_type");
        JsonObject held=body.getAsJsonObject("expected_held_item");
        String weapon=held==null?"":ClientActionRequest.string(held,"id");
        require(ranged?weapon.equals("minecraft:bow"):weapon.matches("minecraft:(wooden|stone|iron|golden|diamond|netherite)_axe"),"target_scope_nonsweeping_axe_or_bow_required");
        require((ranged?RANGED:MELEE).contains(type),"target_scope_type_or_mode_forbidden");
        Set<String> required=new HashSet<>(Set.of("action","action_id","target_entity_id","target_uuid","target_type","min_health","timeout_ms",
            "capability_guard","expected_world_generation","expected_dimension","expected_player_uuid","expected_action_session","expected_hotbar_slot","expected_held_item"));
        if(ranged)required.add("draw_ticks");
        if(type.equals("minecraft:ender_dragon"))required.add("expected_dragon_phase");
        if(type.equals("minecraft:enderman"))required.add("enderman_shelter_required");
        if(type.equals("minecraft:creeper"))required.add("creeper_safety_required");
        if(type.equals("minecraft:cave_spider"))required.add("poison_guard_required");
        if(type.equals("minecraft:blaze")){
            required.add("blaze_safety_mode");
            required.add(body.has("blaze_safety_mode")&&body.get("blaze_safety_mode").getAsString().equals("shield_window")?"expected_offhand_item":"fire_resistance_required");
        }
        var navigation=new HashSet<>(required);navigation.add("expected_navigation_epoch");navigation.add("expected_origin");
        require(body.keySet().equals(required)||body.keySet().equals(navigation),"target_scope_closed_intent");
        for(String key:Set.of("target_entity_id","timeout_ms","expected_hotbar_slot"))strictInteger(body,key);
        if(ranged){strictInteger(body,"draw_ticks");require(body.get("draw_ticks").getAsInt()==20,"target_scope_full_draw_20");}
        if(body.has("expected_dragon_phase"))strictInteger(body,"expected_dragon_phase");
        if(body.has("expected_navigation_epoch"))strictInteger(body,"expected_navigation_epoch");
        JsonObject guard=body.getAsJsonObject("capability_guard");
        require(guard!=null&&guard.keySet().equals(Set.of("schema_version","source_tick","source_nano")),"target_scope_planning_guard");
        strictInteger(guard,"schema_version");strictInteger(guard,"source_tick");
        require(guard.get("schema_version").getAsInt()==1&&guard.get("source_nano").isJsonPrimitive()
            &&guard.get("source_nano").getAsJsonPrimitive().isString()&&guard.get("source_nano").getAsString().matches("-?(0|[1-9][0-9]{0,18})"),"target_scope_planning_guard");
        double minimum=CapabilityCombatSafety.minimum(body,8);
        require(!type.equals("minecraft:end_crystal")||minimum>=12,"target_scope_crystal_reserve_12");
        for(String key:Set.of("enderman_shelter_required","creeper_safety_required","poison_guard_required","fire_resistance_required"))
            if(body.has(key))require(body.get(key).isJsonPrimitive()&&body.get(key).getAsJsonPrimitive().isBoolean()&&body.get(key).getAsBoolean(),"target_scope_species_policy_required");
    }
    private static void strictInteger(JsonObject body,String key){var v=body.get(key);require(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&v.getAsString().matches("0|[1-9][0-9]*"),"target_scope_integer_"+key);}
    private void captureStation(Minecraft mc){
        require(Math.abs(origin.y-Math.rint(origin.y))<=.03,"target_scope_full_height_station_required");
        for(int x=(int)Math.floor(origin.x-.31);x<=(int)Math.floor(origin.x+.31);x++)
            for(int z=(int)Math.floor(origin.z-.31);z<=(int)Math.floor(origin.z+.31);z++)
                for(int y=(int)Math.floor(origin.y)-1;y<=(int)Math.floor(origin.y)+1;y++){
                    BlockPos pos=new BlockPos(x,y,z);station.add(pos);stationStates.add(readStation(mc,pos));
                }
    }
    private BlockState readStation(Minecraft mc,BlockPos pos){
        require(level.hasChunkAt(pos),"target_scope_station_unloaded");BlockState state=level.getBlockState(pos);
        require(state.getFluidState().isEmpty(),"target_scope_station_fluid");
        if(pos.getY()<origin.y-.1)require(CapabilityPath.support(mc,pos)&&state.isCollisionShapeFullBlock(level,pos),"target_scope_full_support_required");
        else require(state.isAir()&&state.getCollisionShape(level,pos).isEmpty(),"target_scope_body_station_blocked");
        return state;
    }
    JsonObject facts(){return captured.deepCopy();}
    private JsonObject factsNow(){
        JsonObject f=new JsonObject();f.addProperty("profile",PROFILE);f.addProperty("action",body.get("action").getAsString());
        for(String key:Set.of("target_entity_id","target_uuid","target_type","min_health","timeout_ms"))f.add(key,body.get(key).deepCopy());
        f.addProperty("alive",target.isAlive());f.addProperty("target_health",target instanceof LivingEntity living?living.getHealth():0);
        f.addProperty("x",target.getX());f.addProperty("y",target.getY());f.addProperty("z",target.getZ());
        f.addProperty("station_x",origin.x);f.addProperty("station_y",origin.y);f.addProperty("station_z",origin.z);
        f.addProperty("ranged",ranged);f.addProperty("shield_window",shield);f.addProperty("draw_ticks",ranged?20:0);
        f.addProperty("dragon_phase",target instanceof EnderDragon d?d.getPhaseManager().getCurrentPhase().getPhase().getId():-1);
        f.addProperty("selected_slot",selected);f.addProperty("support_complete",true);f.addProperty("station_cells",station.size());
        f.addProperty("deadline_nano",Long.toString(deadline));f.addProperty("maximum_offense_effects",1);
        f.addProperty("maximum_offense_packets",1);f.addProperty("automatic_replay_allowed",false);
        f.add("species",speciesFacts());
        JsonArray cells=new JsonArray();for(int i=0;i<station.size();i++){
            BlockPos pos=station.get(i);BlockState state=level.getBlockState(pos);JsonObject c=new JsonObject();
            c.addProperty("x",pos.getX());c.addProperty("y",pos.getY());c.addProperty("z",pos.getZ());
            c.addProperty("id",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
            c.addProperty("loaded",level.hasChunkAt(pos));c.addProperty("fluid_empty",state.getFluidState().isEmpty());
            c.addProperty("support",pos.getY()<origin.y-.1);c.addProperty("full_collision",state.isCollisionShapeFullBlock(level,pos));
            c.addProperty("air",state.isAir());cells.add(c);
        }f.add("support_cells",cells);
        JsonArray rows=new JsonArray();int scanned=0;for(Entity entity:level.entitiesForRendering()){
            require(++scanned<=1024,"target_scope_entity_coverage");requireEntityReaders(entity);JsonObject row=new JsonObject();
            row.addProperty("id",entity.getId());row.addProperty("uuid",entity.getUUID().toString());
            row.addProperty("type",BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
            row.addProperty("x",entity.getX());row.addProperty("y",entity.getY());row.addProperty("z",entity.getZ());
            row.addProperty("alive",entity.isAlive());row.addProperty("living",entity instanceof LivingEntity);
            row.addProperty("projectile",entity instanceof net.minecraft.world.entity.projectile.Projectile);
            var box=entity.getBoundingBox();JsonArray bounds=new JsonArray();
            for(double v:new double[]{box.minX,box.minY,box.minZ,box.maxX,box.maxY,box.maxZ})bounds.add(v);
            row.add("aabb",bounds);rows.add(row);
        }JsonObject frame=new JsonObject();frame.addProperty("complete",true);frame.addProperty("count",scanned);frame.add("entities",rows);f.add("entity_frame",frame);
        return f;
    }
    private JsonObject speciesFacts(){
        JsonObject p=new JsonObject();p.addProperty("type",body.get("target_type").getAsString());
        if(target instanceof net.minecraft.world.entity.monster.EnderMan)p.addProperty("shelter_safe",CapabilityShelter.safe(Minecraft.getInstance()));
        if(target instanceof net.minecraft.world.entity.monster.Creeper c){p.addProperty("powered",c.isPowered());p.addProperty("ignited",c.isIgnited());
            p.addProperty("swell",c.swell);p.addProperty("swell_direction",c.getSwellDir());p.addProperty("fuse_ticks",c.maxSwell);p.addProperty("explosion_radius",c.explosionRadius);}
        if(target instanceof net.minecraft.world.entity.monster.CaveSpider)p.addProperty("poisoned",player.hasEffect(net.minecraft.world.effect.MobEffects.POISON));
        if(target instanceof net.minecraft.world.entity.monster.Blaze b){p.addProperty("charged",b.isCharged());p.addProperty("mode",body.get("blaze_safety_mode").getAsString());
            var resistance=player.getEffect(net.minecraft.world.effect.MobEffects.FIRE_RESISTANCE);p.addProperty("fire_resistance_ticks",resistance==null?0:resistance.isInfiniteDuration()?-1:resistance.getDuration());}
        if(target instanceof net.minecraft.world.entity.monster.Shulker sh)p.addProperty("shell_open",CapabilityTargetAction.shulkerShellOpen(sh));
        if(target instanceof EnderDragon d){p.addProperty("phase",d.getPhaseManager().getCurrentPhase().getPhase().getId());
            Entity head=executor.hitTarget();p.addProperty("head_entity_id",head==null?-1:head.getId());}
        return p;
    }
    void admission(Minecraft mc){
        identity(mc,true,false);String p=executor.policyGuard(mc,false);require(p==null,p);
        ExternalControllerGuard.requireIdle(mc);NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
        require(captured.equals(factsNow()),"target_scope_capture_changed");
        require(body.getAsJsonObject("capability_guard").get("source_tick").getAsLong()<=level.getGameTime()
            &&body.getAsJsonObject("capability_guard").get("source_nano").getAsLong()<=startNano,"target_scope_future_guard");
    }
    void activate(ActionRegistry.Entry e){
        require(entry==null&&e!=null,"target_scope_activation_reused");entry=e;ownerRevision=ClientActions.ownershipRevision();
        require(ClientActions.ownsScopedTarget(this,e),"target_scope_activation_owner_changed");
    }
    void check(Minecraft mc,boolean requireAlive){
        rawBound(mc);identity(mc,requireAlive,true);String p=executor.policyGuard(mc,!requireAlive);require(p==null,p);
        ExternalControllerGuard.requireIdle(mc);rawBound(mc);
    }
    void beforeEffect(Minecraft mc,TargetActionEffectBudget.Effect effect){
        boolean offense=effect==TargetActionEffectBudget.Effect.MELEE||effect==TargetActionEffectBudget.Effect.BOW_RELEASE||effect==TargetActionEffectBudget.Effect.DRAW;
        check(mc,offense);
        if(offense){String p=executor.effectGuard(mc,effect);require(p==null,p);}
        rawBound(mc);
    }
    private void requirePlayerReaders(){
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class
            &&player.inventoryMenu.getClass()==net.minecraft.world.inventory.InventoryMenu.class
            &&player.containerMenu==player.inventoryMenu
            &&level.getChunkSource().getClass()==net.minecraft.client.multiplayer.ClientChunkCache.class
            &&level.getLevelData().getClass()==ClientLevel.ClientLevelData.class
            &&player.getActiveEffectsMap().getClass()==java.util.HashMap.class,
            "target_scope_mutable_reader_unknown");
        require(player.getInventory().items.getClass()==net.minecraft.core.NonNullList.class
            &&player.getInventory().armor.getClass()==net.minecraft.core.NonNullList.class
            &&player.getInventory().offhand.getClass()==net.minecraft.core.NonNullList.class,"target_scope_inventory_list_reader_unknown");
        require(player.getFoodData().getClass()==net.minecraft.world.food.FoodData.class
            &&player.getAbilities().getClass()==net.minecraft.world.entity.player.Abilities.class
            &&player.getAttributes().getClass()==net.minecraft.world.entity.ai.attributes.AttributeMap.class,
            "target_scope_player_reader_unknown");
        for(var attribute:List.of(net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_KNOCKBACK,
                net.minecraft.world.entity.ai.attributes.Attributes.ENTITY_INTERACTION_RANGE,
                net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_SPEED,
                net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_DAMAGE)){
            var value=player.getAttribute(attribute);
            require(value!=null&&value.getClass()==net.minecraft.world.entity.ai.attributes.AttributeInstance.class
                &&value.getAttribute()==attribute&&attribute.getClass()==net.minecraft.core.Holder.Reference.class
                &&attribute.value().getClass()==net.minecraft.world.entity.ai.attributes.RangedAttribute.class,"target_scope_attribute_reader_unknown");
        }
    }
    private void requireTargetClass(){
        Class<?> expected=switch(body.get("target_type").getAsString()){
            case "minecraft:zombie" -> net.minecraft.world.entity.monster.Zombie.class;
            case "minecraft:husk" -> net.minecraft.world.entity.monster.Husk.class;
            case "minecraft:zombie_villager" -> net.minecraft.world.entity.monster.ZombieVillager.class;
            case "minecraft:skeleton" -> net.minecraft.world.entity.monster.Skeleton.class;
            case "minecraft:stray" -> net.minecraft.world.entity.monster.Stray.class;
            case "minecraft:bogged" -> net.minecraft.world.entity.monster.Bogged.class;
            case "minecraft:spider" -> net.minecraft.world.entity.monster.Spider.class;
            case "minecraft:shulker" -> net.minecraft.world.entity.monster.Shulker.class;
            case "minecraft:enderman" -> net.minecraft.world.entity.monster.EnderMan.class;
            case "minecraft:creeper" -> net.minecraft.world.entity.monster.Creeper.class;
            case "minecraft:cave_spider" -> net.minecraft.world.entity.monster.CaveSpider.class;
            case "minecraft:blaze" -> net.minecraft.world.entity.monster.Blaze.class;
            case "minecraft:ender_dragon" -> EnderDragon.class;
            case "minecraft:end_crystal" -> net.minecraft.world.entity.boss.enderdragon.EndCrystal.class;
            default -> null;
        };require(expected!=null&&target.getClass()==expected,"target_scope_exact_target_class_required");
    }
    void afterMelee(Minecraft mc){check(mc,false);}
    private void identity(Minecraft mc,boolean alive,boolean activated){
        requirePlayerReaders();requireTargetClass();requireEntityReaders(target);requireEntityReaders(player);
        require(mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server
            &&mc.options==options&&mc.options.keyUse==useKey
            &&CapabilityGuard.privateSingleplayer(mc)&&session.equals(ClientActions.session())&&WorldGeneration.matches(level,world)
            &&mc.screen==null&&!mc.isPaused()&&mc.isWindowActive()&&System.nanoTime()<deadline,"target_scope_context_or_deadline_changed");
        require(player.isAlive()&&!player.isSpectator()&&!player.getAbilities().flying&&!player.getAbilities().mayfly
            &&!player.getAbilities().instabuild&&!player.getAbilities().invulnerable&&!player.noPhysics
            &&((net.minecraft.client.multiplayer.MultiPlayerGameMode)gameMode).getPlayerMode()==net.minecraft.world.level.GameType.SURVIVAL
            &&player.onGround()&&!player.isSprinting()&&!player.isShiftKeyDown()&&player.getPose()==net.minecraft.world.entity.Pose.STANDING
            &&player.containerMenu==player.inventoryMenu&&player.containerMenu.getCarried().isEmpty()
            &&player.position().distanceTo(origin)<=.03,"target_scope_station_pose_changed");
        Entity mapped=level.getEntity(ClientActionRequest.integer(body,"target_entity_id",-1));
        require((mapped==target||!alive&&mapped==null&&(target.isRemoved()||!target.isAlive()))
            &&target.getUUID().toString().equals(body.get("target_uuid").getAsString())
            &&BuiltInRegistries.ENTITY_TYPE.getKey(target.getType()).toString().equals(body.get("target_type").getAsString())
            &&(!alive||target.isAlive())&&!player.isAlliedTo(target),"target_scope_exact_target_changed");
        require(player.getInventory().selected==selected,"target_scope_selected_slot_changed");
        ItemStack selectedItem=player.getMainHandItem();String weapon=BuiltInRegistries.ITEM.getKey(selectedItem.getItem()).toString();
        require(selectedItem.getCount()==1&&(ranged?selectedItem.is(Items.BOW):weapon.matches("minecraft:(wooden|stone|iron|golden|diamond|netherite)_axe")
            &&(selectedItem.getItem() instanceof net.minecraft.world.item.AxeItem)),"target_scope_vanilla_weapon_required");
        require(ranged?selectedItem.getItem().getClass()==net.minecraft.world.item.BowItem.class:
            selectedItem.getItem().getClass()==net.minecraft.world.item.AxeItem.class,
            "target_scope_exact_weapon_class_required");
        if(!ranged)require(player.getAttributeValue(net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_KNOCKBACK)==0,"target_scope_zero_local_knockback_required");
        for(EquipmentSlot slot:EquipmentSlot.values()){
            ItemStack initial=equipment.get(slot),current=player.getItemBySlot(slot).copy();
            require(current.getDamageValue()>=initial.getDamageValue(),"target_scope_equipment_damage_regressed");
            if(current.isDamageableItem())current.setDamageValue(initial.getDamageValue());
            boolean spentOffhandArrow=ranged&&slot==EquipmentSlot.OFFHAND&&initial.is(Items.ARROW)
                &&budget.local(TargetActionEffectBudget.Effect.BOW_RELEASE)==1&&current.getCount()==initial.getCount()-1
                &&(current.isEmpty()&&initial.getCount()==1||ItemStack.isSameItemSameComponents(current,initial));
            require(spentOffhandArrow||CapabilityItemBinding.same(current,initial),"target_scope_equipment_changed");
        }
        if(ranged&&budget.local(TargetActionEffectBudget.Effect.BOW_RELEASE)==0)
            require(CapabilityItemBinding.same(player.getProjectile(player.getMainHandItem()),ammunition),"target_scope_ammunition_changed");
        for(int i=0;i<station.size();i++)require(readStation(mc,station.get(i))==stationStates.get(i),"target_scope_support_changed");
        if(activated)rawBound(mc);
    }
    void rawBound(Minecraft mc){
        NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
        boolean serverBound=mc.getSingleplayerServer()==server&&CapabilityGuard.privateSingleplayer(mc)
            &&mc.isSameThread()&&!mc.isPaused()&&mc.isWindowActive();
        require(serverBound&&entry!=null&&ClientActions.ownsScopedTarget(this,entry)&&ClientActions.ownershipRevision()==ownerRevision
            &&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.screen==null
            &&mc.options==options&&mc.options.keyUse==useKey
            &&System.nanoTime()<deadline&&session.equals(ClientActions.session())&&WorldGeneration.matches(level,world),"target_scope_final_owner_context_deadline");
        NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
    }
    record EntityGeometry(Entity identity,int id,java.util.UUID uuid,Object type,boolean alive,boolean removed,
        double x,double y,double z,net.minecraft.world.phys.AABB box,float health,String species,Object projectileOwner,Vec3 velocity){}
    record HitGeometry(Entity identity,double x,double y,double z,net.minecraft.world.phys.AABB box){}
    record PlayerGeometry(float health,Object pose,boolean ground,boolean water,boolean lava,boolean fire,boolean powder,
        boolean sprint,boolean crouch,boolean using,Object usedHand,StackGeometry useItem,boolean alive,boolean spectator){}
    record Geometry(double x,double y,double z,float yaw,float pitch,Object hit,HitGeometry hitTarget,PlayerGeometry playerFacts,List<EntityGeometry> entities,
        List<StackGeometry> equipment,List<StackGeometry> inventory,PolicyGeometry policy,List<BlockState> cells){}
    /** Only identity tokens and primitive bits. Never delegates to a component/holder equals method. */
    record PolicyGeometry(List<Object> identities,List<Long> values){}
    static boolean samePolicyGeometry(PolicyGeometry a,PolicyGeometry b){
        if(!TargetActionReaderPolicy.sameIdentityValues(a.identities,b.identities)||a.values.size()!=b.values.size())return false;
        for(int i=0;i<a.values.size();i++)if(a.values.get(i).longValue()!=b.values.get(i).longValue())return false;
        return true;
    }
    record StackGeometry(ItemStack identity,Object item,int count,List<Object> componentTypes,List<Object> componentValues){}
    private static StackGeometry stackGeometry(ItemStack stack){
        require(stack!=null&&stack.getClass()==ItemStack.class,"target_scope_stack_reader_unknown");
        require(TargetActionReaderPolicy.declaredBy(stack.getItem().getClass(),"components",net.minecraft.world.item.Item.class),"target_scope_item_component_reader_unknown");
        var prototype=stack.getPrototype();Class<?> type=prototype.getClass();
        require(prototype==net.minecraft.core.component.DataComponentMap.EMPTY
            ||type.getName().equals("net.minecraft.core.component.DataComponentMap$Builder$SimpleMap")
                &&type.getClassLoader()==net.minecraft.core.component.DataComponentMap.class.getClassLoader(),"target_scope_component_prototype_unknown");
        var map=stack.getComponents();require(map==net.minecraft.core.component.DataComponentMap.EMPTY
            ||map.getClass()==net.minecraft.core.component.PatchedDataComponentMap.class,"target_scope_component_map_unknown");
        var types=new ArrayList<Object>();var values=new ArrayList<Object>();
        for(var component:map){require(types.size()<256,"target_scope_component_coverage");types.add(component.type());values.add(component.value());}
        return new StackGeometry(stack,stack.getItem(),stack.getCount(),List.copyOf(types),List.copyOf(values));
    }
    static StackGeometry argumentStack(ItemStack stack){return stackGeometry(stack);}
    static void unchangedArgument(StackGeometry before,ItemStack after){
        require(sameStackGeometry(before,stackGeometry(after)),"target_scope_effect_argument_changed");
    }
    private static boolean sameStackGeometry(StackGeometry a,StackGeometry b){
        if(a.identity!=b.identity||a.item!=b.item||a.count!=b.count||a.componentTypes.size()!=b.componentTypes.size())return false;
        return TargetActionReaderPolicy.sameIdentityValues(a.componentTypes,b.componentTypes)
            &&TargetActionReaderPolicy.sameIdentityValues(a.componentValues,b.componentValues); // Never call arbitrary component-value equals/hashCode in the final fence.
    }
    private static boolean sameEntityGeometry(EntityGeometry a,EntityGeometry b){
        return a.identity==b.identity&&a.id==b.id&&a.uuid.equals(b.uuid)&&a.type==b.type&&a.alive==b.alive&&a.removed==b.removed
            &&a.x==b.x&&a.y==b.y&&a.z==b.z&&a.box.equals(b.box)&&a.health==b.health&&a.species.equals(b.species)
            &&a.projectileOwner==b.projectileOwner&&a.velocity.x==b.velocity.x&&a.velocity.y==b.velocity.y&&a.velocity.z==b.velocity.z;
    }
    private static boolean sameHitGeometry(HitGeometry a,HitGeometry b){
        return a==null?b==null:b!=null&&a.identity==b.identity&&a.x==b.x&&a.y==b.y&&a.z==b.z&&a.box.equals(b.box);
    }
    /** All final snapshot accessors must be known field/data readers, before any are invoked.
     * In particular, an overridden late getHealth cannot mutate an earlier sampled entity.
     * Unknown entity subclasses may participate only when every used getter is inherited
     * unchanged; species-specific readers require the exact vanilla species class.
     */
    private static void requireEntityReaders(Entity entity){
        require(entity!=null,"target_scope_entity_reader_missing");Class<?> type=entity.getClass();
        for(String name:List.of("getId","getUUID","getType","getEntityData","position","level","getBoundingBox","getX","getY","getZ","isRemoved"))
            require(TargetActionReaderPolicy.declaredBy(type,name,Entity.class),"target_scope_entity_reader_unknown");
        require(TargetActionReaderPolicy.declaredBy(type,"isAlive",entity instanceof LivingEntity?LivingEntity.class:Entity.class),
            "target_scope_alive_reader_unknown");
        if(entity instanceof LivingEntity)require(TargetActionReaderPolicy.declaredBy(type,"getHealth",LivingEntity.class),"target_scope_health_reader_unknown");
        require(entity.level()==Minecraft.getInstance().level,"target_scope_entity_level_changed");
        require(entity.getEntityData().getClass()==net.minecraft.network.syncher.SynchedEntityData.class,"target_scope_entity_data_reader_unknown");
        require(entity.getBoundingBox().getClass()==net.minecraft.world.phys.AABB.class&&entity.position().getClass()==Vec3.class,
            "target_scope_exact_geometry_data_required");
        require(TargetActionReaderPolicy.entityVelocityReader(type),"target_scope_velocity_reader_unknown");
        require(entity.getDeltaMovement().getClass()==Vec3.class,"target_scope_velocity_reader_unknown");
        if(entity instanceof net.minecraft.world.entity.projectile.Projectile)
            require(TargetActionReaderPolicy.declaredBy(type,"getOwner",net.minecraft.world.entity.projectile.Projectile.class),"target_scope_projectile_owner_reader_unknown");
        if(entity instanceof net.minecraft.world.entity.monster.Creeper)require(type==net.minecraft.world.entity.monster.Creeper.class,"target_scope_species_reader_unknown");
        if(entity instanceof net.minecraft.world.entity.monster.Blaze)require(type==net.minecraft.world.entity.monster.Blaze.class,"target_scope_species_reader_unknown");
        if(entity instanceof net.minecraft.world.entity.monster.EnderMan)require(type==net.minecraft.world.entity.monster.EnderMan.class,"target_scope_species_reader_unknown");
        if(entity instanceof net.minecraft.world.entity.monster.Shulker)require(type==net.minecraft.world.entity.monster.Shulker.class,"target_scope_species_reader_unknown");
        if(entity instanceof EnderDragon dragon){
            require(type==EnderDragon.class,"target_scope_species_reader_unknown");
            var manager=dragon.getPhaseManager();
            require(manager.getClass()==net.minecraft.world.entity.boss.enderdragon.phases.EnderDragonPhaseManager.class,"target_scope_dragon_manager_reader_unknown");
            var phase=manager.getCurrentPhase();
            require(Set.of(net.minecraft.world.entity.boss.enderdragon.phases.DragonHoldingPatternPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonStrafePlayerPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonLandingApproachPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonLandingPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonTakeoffPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonSittingFlamingPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonSittingScanningPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonSittingAttackingPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonChargePlayerPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonDeathPhase.class,
                net.minecraft.world.entity.boss.enderdragon.phases.DragonHoverPhase.class).contains(phase.getClass()),"target_scope_exact_dragon_phase_reader_required");
        }
        if(entity instanceof EnderDragonPart)require(type==EnderDragonPart.class,"target_scope_head_reader_unknown");
    }
    Geometry geometry(){
        requirePlayerReaders();
        var entities=new ArrayList<EntityGeometry>();var seen=new java.util.IdentityHashMap<Entity,Boolean>();
        var ids=new HashSet<Integer>();var uuids=new HashSet<java.util.UUID>();
        for(Entity entity:level.entitiesForRendering()){
            require(entities.size()<1024&&entity!=null&&seen.put(entity,Boolean.TRUE)==null,"target_scope_entity_coverage");
            requireEntityReaders(entity);
            int id=entity.getId();java.util.UUID uuid=entity.getUUID();
            require(ids.add(id)&&uuids.add(uuid),"target_scope_duplicate_entity_identity");
            String species="";
            if(entity instanceof net.minecraft.world.entity.monster.Creeper c)species=c.isPowered()+":"+c.isIgnited()+":"+c.swell+":"+c.getSwellDir()+":"+c.maxSwell+":"+c.explosionRadius;
            else if(entity instanceof net.minecraft.world.entity.monster.Blaze b)species=Boolean.toString(b.isCharged());
            else if(entity instanceof net.minecraft.world.entity.monster.EnderMan e)species=e.isCreepy()+":"+e.hasBeenStaredAt();
            else if(entity instanceof net.minecraft.world.entity.monster.Shulker sh)species=sh.getRawPeekAmount()+":"+sh.getClientPeekAmount(1.0F);
            else if(entity instanceof EnderDragon d)species=Integer.toString(d.getPhaseManager().getCurrentPhase().getPhase().getId());
            if(entity instanceof LivingEntity living)require(Float.isFinite(living.getHealth())&&living.getHealth()>=0,"target_scope_invalid_entity_health");
            entities.add(new EntityGeometry(entity,id,uuid,entity.getType(),entity.isAlive(),entity.isRemoved(),
                entity.getX(),entity.getY(),entity.getZ(),entity.getBoundingBox(),entity instanceof LivingEntity l?l.getHealth():0,species,
                entity instanceof net.minecraft.world.entity.projectile.Projectile projectile?projectile.getOwner():null,entity.getDeltaMovement()));
        }
        require(seen.containsKey(player),"target_scope_player_entity_coverage");
        var stacks=new ArrayList<StackGeometry>();for(EquipmentSlot slot:EquipmentSlot.values())stacks.add(stackGeometry(player.getItemBySlot(slot)));
        var inventory=new ArrayList<StackGeometry>();
        for(int i=0;i<player.getInventory().getContainerSize();i++){
            require(i<41,"target_scope_inventory_coverage");inventory.add(stackGeometry(player.getInventory().getItem(i)));
        }
        require(inventory.size()==41,"target_scope_inventory_coverage");inventory.add(stackGeometry(player.inventoryMenu.getCarried()));
        requireMenuReaders();for(var slot:player.inventoryMenu.slots)inventory.add(stackGeometry(slot.getItem()));
        var cells=new ArrayList<BlockState>();var policy=policyGeometry(cells);
        Entity hit=executor.hitTarget();if(hit!=null)requireEntityReaders(hit);HitGeometry hitGeometry=hit==null?null:new HitGeometry(hit,hit.getX(),hit.getY(),hit.getZ(),hit.getBoundingBox());
        PlayerGeometry playerFacts=new PlayerGeometry(player.getHealth(),player.getPose(),player.onGround(),player.isInWater(),player.isInLava(),player.isOnFire(),
            player.isInPowderSnow,player.isSprinting(),player.isShiftKeyDown(),player.isUsingItem(),player.getUsedItemHand(),stackGeometry(player.getUseItem()),player.isAlive(),player.isSpectator());
        return new Geometry(player.getX(),player.getY(),player.getZ(),player.getYRot(),player.getXRot(),Minecraft.getInstance().hitResult,hitGeometry,playerFacts,
            List.copyOf(entities),List.copyOf(stacks),List.copyOf(inventory),policy,List.copyOf(cells));
    }
    private void requireMenuReaders(){
        var slots=player.inventoryMenu.slots;
        require(slots.getClass()==net.minecraft.core.NonNullList.class&&slots.size()==46,"target_scope_menu_slot_coverage");
        for(var slot:slots){
            require(TargetActionReaderPolicy.declaredBy(slot.getClass(),"getItem",net.minecraft.world.inventory.Slot.class)
                &&TargetActionReaderPolicy.declaredBy(slot.getClass(),"getContainerSlot",net.minecraft.world.inventory.Slot.class),"target_scope_slot_reader_unknown");
            Class<?> container=slot.container.getClass();
            require(container==net.minecraft.world.entity.player.Inventory.class
                ||container==net.minecraft.world.inventory.TransientCraftingContainer.class
                ||container==net.minecraft.world.inventory.ResultContainer.class,"target_scope_slot_container_reader_unknown");
        }
    }
    private PolicyGeometry policyGeometry(List<BlockState> cells){
        var ids=new ArrayList<Object>();var bits=new ArrayList<Long>();
        var inventory=player.getInventory();var abilities=player.getAbilities();
        ids.add(inventory);ids.add(player.inventoryMenu);ids.add(player.containerMenu);ids.add(abilities);
        ids.add(player.getAttributes());ids.add(player.getEntityData());ids.add(level.getChunkSource());ids.add(level.getLevelData());
        ids.add(level.getEntity(ClientActionRequest.integer(body,"target_entity_id",-1)));
        ids.add(((net.minecraft.client.multiplayer.MultiPlayerGameMode)gameMode).getPlayerMode());
        bits.add((long)inventory.selected);bits.add((long)player.inventoryMenu.containerId);bits.add((long)player.inventoryMenu.getStateId());
        ids.add(player.inventoryMenu.slots);for(var slot:player.inventoryMenu.slots){
            ids.add(slot);ids.add(slot.container);bits.add((long)slot.index);bits.add((long)slot.getContainerSlot());
        }
        bits.add((long)player.hurtTime);ids.add(player.getFoodData());bits.add((long)player.getFoodData().getFoodLevel());
        bits.add((long)Float.floatToRawIntBits(player.getFoodData().getSaturationLevel()));
        var mc=Minecraft.getInstance();
        TargetActionKeySnapshot.appendStationary(mc.options,entry!=null&&executor.ownsUseInput(),ids,bits);
        // Raw bridge keys/buttons are never part of this stationary owner's input.
        // heldInputsSnapshot invokes NeoForge key callbacks; do not use it here.
        require(!BridgeServer.hasHeldInputs(),"target_scope_raw_input_held");
        var input=player.input;ids.add(input);if(input!=null){
            bits.add((long)Float.floatToRawIntBits(input.forwardImpulse));bits.add((long)Float.floatToRawIntBits(input.leftImpulse));
            bits.add(input.up?1L:0L);bits.add(input.down?1L:0L);bits.add(input.left?1L:0L);bits.add(input.right?1L:0L);
            bits.add(input.jumping?1L:0L);bits.add(input.shiftKeyDown?1L:0L);
        }
        bits.add((long)player.getTicksFrozen());bits.add((long)player.getUseItemRemainingTicks());
        bits.add((long)Float.floatToRawIntBits(player.getAttackStrengthScale(.5F)));
        bits.add(abilities.flying?1L:0L);bits.add(abilities.mayfly?1L:0L);bits.add(abilities.instabuild?1L:0L);
        bits.add(abilities.invulnerable?1L:0L);bits.add(player.noPhysics?1L:0L);
        for(var attribute:List.of(net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_KNOCKBACK,
                net.minecraft.world.entity.ai.attributes.Attributes.ENTITY_INTERACTION_RANGE,
                net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_SPEED,
                net.minecraft.world.entity.ai.attributes.Attributes.ATTACK_DAMAGE)){
            var value=player.getAttribute(attribute);ids.add(attribute);ids.add(value);
            double number=value.getValue();require(Double.isFinite(number),"target_scope_attribute_nonfinite");
            bits.add(Double.doubleToRawLongBits(number));
        }
        var scoreboard=level.getScoreboard();require(scoreboard.getClass()==net.minecraft.world.scores.Scoreboard.class,"target_scope_scoreboard_reader_unknown");
        var playerTeam=player.getTeam();var targetTeam=target.getTeam();
        require((playerTeam==null||playerTeam.getClass()==net.minecraft.world.scores.PlayerTeam.class)
            &&(targetTeam==null||targetTeam.getClass()==net.minecraft.world.scores.PlayerTeam.class),"target_scope_team_reader_unknown");
        ids.add(scoreboard);ids.add(playerTeam);ids.add(targetTeam);bits.add(player.isAlliedTo(target)?1L:0L);
        var effects=player.getActiveEffectsMap();ids.add(effects);bits.add((long)effects.size());
        require(effects.size()<=64,"target_scope_effect_coverage");
        for(var effect:effects.entrySet()){
            require(effect.getKey().getClass()==net.minecraft.core.Holder.Reference.class
                &&effect.getValue().getClass()==net.minecraft.world.effect.MobEffectInstance.class,"target_scope_effect_reader_unknown");
            ids.add(effect.getKey());ids.add(effect.getValue());ids.add(effect.getValue().getEffect());
            bits.add((long)effect.getValue().getDuration());bits.add((long)effect.getValue().getAmplifier());
        }
        // Purely re-evaluate the immutable calm/targetless observation predicate,
        // including freshness. Unrelated server-batch publication is not an input.
        var living=NativeLivingObservation.capture(Minecraft.getInstance());ids.add(living.context());
        for(Entity entity:level.entitiesForRendering())if(entity instanceof net.minecraft.world.entity.monster.EnderMan){
            ids.add(entity);bits.add(NativeLivingObservation.knownCalmTargetless(Minecraft.getInstance(),entity,living)?1L:0L);
        }
        Entity exactHit=executor.hitTarget();Vec3 eye=player.getEyePosition();
        require(eye.getClass()==Vec3.class,"target_scope_eye_reader_unknown");
        bits.add(Double.doubleToRawLongBits(eye.x));bits.add(Double.doubleToRawLongBits(eye.y));bits.add(Double.doubleToRawLongBits(eye.z));
        var footprint=new java.util.LinkedHashSet<BlockPos>(station);
        if(target instanceof net.minecraft.world.entity.monster.EnderMan){
            BlockPos feet=player.blockPosition();for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++)footprint.add(feet.offset(x,2,z));
        }
        if(exactHit!=null){
            if(ranged){
                Vec3 point=exactHit.getBoundingBox().getCenter(),delta=point.subtract(eye);
                double flat=Math.hypot(delta.x,delta.z),elevation=CapabilityTargetPolicy.bowElevation(flat,delta.y);
                require(Double.isFinite(elevation)&&flat>0&&eye.distanceTo(point)<=CapabilityTargetPolicy.MAX_SHOT_DISTANCE,
                    "target_scope_bounded_trajectory_required");
                double time=flat/(3*Math.cos(elevation));Vec3 previous=eye;
                for(int i=1;i<=24;i++){
                    double tick=time*i/24,run=3*Math.cos(elevation)*tick;
                    Vec3 next=new Vec3(eye.x+delta.x/flat*run,eye.y+3*Math.sin(elevation)*tick-.025*tick*tick,eye.z+delta.z/flat*run);
                    addSegment(footprint,previous,next);previous=next;
                }
            }else if(Minecraft.getInstance().hitResult instanceof EntityHitResult ray){
                require(ray.getClass()==EntityHitResult.class&&ray.getLocation().getClass()==Vec3.class,"target_scope_ray_reader_unknown");
                require(eye.distanceTo(ray.getLocation())<=6,"target_scope_bounded_melee_ray_required");addSegment(footprint,eye,ray.getLocation());
            }
        }
        for(BlockPos pos:footprint){
            require(level.hasChunkAt(pos),"target_scope_policy_footprint_unloaded");
            var chunk=level.getChunkSource().getChunk(pos.getX()>>4,pos.getZ()>>4,net.minecraft.world.level.chunk.status.ChunkStatus.FULL,false);
            require(chunk!=null&&chunk.getClass()==net.minecraft.world.level.chunk.LevelChunk.class,"target_scope_chunk_reader_unknown");
            int sectionIndex=chunk.getSectionIndex(pos.getY());
            require(sectionIndex>=0&&sectionIndex<chunk.getSectionsCount(),"target_scope_cell_height_unknown");
            var section=chunk.getSection(sectionIndex);
            require(section!=null&&section.getClass()==net.minecraft.world.level.chunk.LevelChunkSection.class
                &&section.getStates().getClass()==net.minecraft.world.level.chunk.PalettedContainer.class,"target_scope_chunk_section_reader_unknown");
            ids.add(section);ids.add(section.getStates());
            BlockState state=chunk.getBlockState(pos);requirePolicyCell(state);
            bits.add(pos.asLong());ids.add(chunk);cells.add(state);
        }
        // These are null-tolerant identity lists; List.copyOf would reject missing target/batch.
        return new PolicyGeometry(java.util.Collections.unmodifiableList(ids),List.copyOf(bits));
    }
    private static boolean finiteBounded(Vec3 point){
        return Double.isFinite(point.x)&&Double.isFinite(point.y)&&Double.isFinite(point.z)
            &&Math.abs(point.x)<=30_000_000&&Math.abs(point.y)<=1_000_000&&Math.abs(point.z)<=30_000_000;
    }
    static void addSegment(java.util.Set<BlockPos> cells,Vec3 a,Vec3 b){
        require(finiteBounded(a)&&finiteBounded(b)&&a.distanceTo(b)<=64,"target_scope_segment_unbounded");
        // The clip path and its immediate neighbours cover voxel traversal and the
        // corridor's .6 chunk-loading margin. No 32-cubed world scan is performed.
        for(int x=(int)Math.floor(Math.min(a.x,b.x)-1);x<=(int)Math.floor(Math.max(a.x,b.x)+1);x++)
            for(int y=(int)Math.floor(Math.min(a.y,b.y)-1);y<=(int)Math.floor(Math.max(a.y,b.y)+1);y++)
                for(int z=(int)Math.floor(Math.min(a.z,b.z)-1);z<=(int)Math.floor(Math.max(a.z,b.z)+1);z++){
                    require(cells.size()<4096,"target_scope_policy_footprint_budget");cells.add(new BlockPos(x,y,z));
                }
    }
    private static final class PolicyCells { static final Set<net.minecraft.world.level.block.Block> VALUES=Set.of(
        net.minecraft.world.level.block.Blocks.AIR,net.minecraft.world.level.block.Blocks.CAVE_AIR,net.minecraft.world.level.block.Blocks.VOID_AIR,
        net.minecraft.world.level.block.Blocks.STONE,net.minecraft.world.level.block.Blocks.COBBLESTONE,net.minecraft.world.level.block.Blocks.DIRT,
        net.minecraft.world.level.block.Blocks.GRASS_BLOCK,net.minecraft.world.level.block.Blocks.ANDESITE,net.minecraft.world.level.block.Blocks.DIORITE,
        net.minecraft.world.level.block.Blocks.GRANITE,net.minecraft.world.level.block.Blocks.SMOOTH_STONE,net.minecraft.world.level.block.Blocks.STONE_BRICKS,
        net.minecraft.world.level.block.Blocks.BRICKS,net.minecraft.world.level.block.Blocks.DEEPSLATE,net.minecraft.world.level.block.Blocks.COBBLED_DEEPSLATE,
        net.minecraft.world.level.block.Blocks.BEDROCK,net.minecraft.world.level.block.Blocks.SANDSTONE,
        net.minecraft.world.level.block.Blocks.OAK_PLANKS,net.minecraft.world.level.block.Blocks.SPRUCE_PLANKS,net.minecraft.world.level.block.Blocks.BIRCH_PLANKS,
        net.minecraft.world.level.block.Blocks.JUNGLE_PLANKS,net.minecraft.world.level.block.Blocks.ACACIA_PLANKS,net.minecraft.world.level.block.Blocks.DARK_OAK_PLANKS,
        net.minecraft.world.level.block.Blocks.MANGROVE_PLANKS,net.minecraft.world.level.block.Blocks.CHERRY_PLANKS,
        net.minecraft.world.level.block.Blocks.OAK_LOG,net.minecraft.world.level.block.Blocks.SPRUCE_LOG,net.minecraft.world.level.block.Blocks.BIRCH_LOG,
        net.minecraft.world.level.block.Blocks.JUNGLE_LOG,net.minecraft.world.level.block.Blocks.ACACIA_LOG,net.minecraft.world.level.block.Blocks.DARK_OAK_LOG,
        net.minecraft.world.level.block.Blocks.OBSIDIAN,net.minecraft.world.level.block.Blocks.END_STONE,net.minecraft.world.level.block.Blocks.END_STONE_BRICKS,
        net.minecraft.world.level.block.Blocks.NETHERRACK,net.minecraft.world.level.block.Blocks.NETHER_BRICKS,net.minecraft.world.level.block.Blocks.BLACKSTONE,
        net.minecraft.world.level.block.Blocks.POLISHED_BLACKSTONE,net.minecraft.world.level.block.Blocks.BASALT,net.minecraft.world.level.block.Blocks.GLASS,
        net.minecraft.world.level.block.Blocks.GLOWSTONE,net.minecraft.world.level.block.Blocks.SEA_LANTERN,net.minecraft.world.level.block.Blocks.QUARTZ_BLOCK,
        net.minecraft.world.level.block.Blocks.PURPUR_BLOCK,net.minecraft.world.level.block.Blocks.PURPUR_PILLAR); }
    private static void requirePolicyCell(BlockState state){
        var block=state.getBlock();require(state.getClass()==BlockState.class&&PolicyCells.VALUES.contains(block)
            &&block.getClass().getClassLoader()==net.minecraft.world.level.block.Block.class.getClassLoader(),"target_scope_policy_cell_unsupported");
        Class<?> behavior=net.minecraft.world.level.block.state.BlockBehaviour.class;
        Class<?> shape=block instanceof net.minecraft.world.level.block.AirBlock?net.minecraft.world.level.block.AirBlock.class:behavior;
        require(TargetActionReaderPolicy.implementationDeclaredBy(block.getClass(),"getShape",shape,BlockState.class,
                net.minecraft.world.level.BlockGetter.class,BlockPos.class,net.minecraft.world.phys.shapes.CollisionContext.class)
            &&TargetActionReaderPolicy.implementationDeclaredBy(block.getClass(),"getCollisionShape",behavior,BlockState.class,
                net.minecraft.world.level.BlockGetter.class,BlockPos.class,net.minecraft.world.phys.shapes.CollisionContext.class),"target_scope_policy_shape_reader_unknown");
    }
    void finalExternalFence(Geometry before){
        ExternalControllerGuard.requireIdle(Minecraft.getInstance());
        geometryUnchanged(before);rawBound(Minecraft.getInstance());
    }
    void admissionRawFence(Minecraft mc){
        require(entry==null,"target_scope_admission_already_activated");
        compareGeometry(capturedGeometry,geometry());
        NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
        require(mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server
            &&mc.options==options&&mc.options.keyUse==useKey
            &&CapabilityGuard.privateSingleplayer(mc)&&mc.screen==null&&!mc.isPaused()&&mc.isWindowActive()
            &&System.nanoTime()<deadline&&session.equals(ClientActions.session())&&WorldGeneration.matches(level,world),"target_scope_final_admission_context");
        NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
    }
    void geometryUnchanged(Geometry before){compareGeometry(before,geometry());rawBound(Minecraft.getInstance());}
    static void compareGeometry(Geometry before,Geometry after){
        require(before.x==after.x&&before.y==after.y&&before.z==after.z&&before.yaw==after.yaw&&before.pitch==after.pitch
            &&before.hit==after.hit&&sameHitGeometry(before.hitTarget,after.hitTarget)
            &&before.entities.size()==after.entities.size()&&samePolicyGeometry(before.policy,after.policy)
            &&TargetActionReaderPolicy.sameIdentityValues(before.cells,after.cells),"target_scope_geometry_changed_during_hooks");
        PlayerGeometry a=before.playerFacts,b=after.playerFacts;
        require(a.health==b.health&&a.pose==b.pose&&a.ground==b.ground&&a.water==b.water&&a.lava==b.lava&&a.fire==b.fire&&a.powder==b.powder
            &&a.sprint==b.sprint&&a.crouch==b.crouch&&a.using==b.using&&a.usedHand==b.usedHand&&a.alive==b.alive&&a.spectator==b.spectator
            &&sameStackGeometry(a.useItem,b.useItem),"target_scope_player_changed_during_hooks");
        for(int i=0;i<before.entities.size();i++)require(sameEntityGeometry(before.entities.get(i),after.entities.get(i)),"target_scope_entities_changed_during_hooks");
        for(int i=0;i<before.equipment.size();i++)require(sameStackGeometry(before.equipment.get(i),after.equipment.get(i)),"target_scope_equipment_changed_during_hooks");
        require(before.inventory.size()==after.inventory.size(),"target_scope_inventory_changed_during_hooks");
        for(int i=0;i<before.inventory.size();i++)require(sameStackGeometry(before.inventory.get(i),after.inventory.get(i)),"target_scope_inventory_changed_during_hooks");
    }
    void cleanupFence(Minecraft mc){
        require(entry!=null&&ClientActions.terminalTargetCleanup(this,entry)&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode
            &&mc.getSingleplayerServer()==server&&mc.options==options&&mc.options.keyUse==useKey
            &&session.equals(ClientActions.session())&&WorldGeneration.matches(level,world),"target_scope_cleanup_owner_context_changed");
        require(ClientActions.terminalTargetCleanup(this,entry)&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode
            &&mc.options==options&&mc.options.keyUse==useKey,"target_scope_cleanup_final_owner_changed");
    }
    void unknown(){unknown=true;budget.poison();if(entry!=null)entry.result.addProperty("unknown_outcome",true);}
    boolean attempted(){return budget.attempted();}
    boolean completed(){
        return !unknown&&!budget.unknown()
            &&budget.local(TargetActionEffectBudget.Effect.MELEE,TargetActionEffectBudget.Effect.BOW_RELEASE)==1
            &&budget.packets(TargetActionEffectBudget.Effect.MELEE,TargetActionEffectBudget.Effect.BOW_RELEASE)==1
            &&budget.local(TargetActionEffectBudget.Effect.DRAW)==(ranged?1:0)
            &&budget.packets(TargetActionEffectBudget.Effect.DRAW)==(ranged?1:0)
            &&budget.local(TargetActionEffectBudget.Effect.SHIELD_USE)==(shield?2:0)
            &&budget.packets(TargetActionEffectBudget.Effect.SHIELD_USE)==(shield?2:0)
            &&budget.local(TargetActionEffectBudget.Effect.SHIELD_RELEASE)==(shield?2:0)
            &&budget.packets(TargetActionEffectBudget.Effect.SHIELD_RELEASE)==(shield?2:0);
    }
    JsonObject terminal(boolean neutral){
        JsonObject out=new JsonObject();out.addProperty("profile",PROFILE);
        for(String key:Set.of("target_entity_id","target_uuid","target_type"))out.add(key,body.get(key).deepCopy());
        out.addProperty("offense_effects",budget.local(TargetActionEffectBudget.Effect.MELEE,TargetActionEffectBudget.Effect.BOW_RELEASE));
        out.addProperty("offense_packets",budget.packets(TargetActionEffectBudget.Effect.MELEE,TargetActionEffectBudget.Effect.BOW_RELEASE));
        out.addProperty("draw_effects",budget.local(TargetActionEffectBudget.Effect.DRAW));out.addProperty("draw_packets",budget.packets(TargetActionEffectBudget.Effect.DRAW));
        out.addProperty("shield_use_effects",budget.local(TargetActionEffectBudget.Effect.SHIELD_USE));out.addProperty("shield_use_packets",budget.packets(TargetActionEffectBudget.Effect.SHIELD_USE));
        out.addProperty("shield_release_effects",budget.local(TargetActionEffectBudget.Effect.SHIELD_RELEASE,TargetActionEffectBudget.Effect.SHIELD_CLEANUP));
        out.addProperty("shield_release_packets",budget.packets(TargetActionEffectBudget.Effect.SHIELD_RELEASE,TargetActionEffectBudget.Effect.SHIELD_CLEANUP));
        out.addProperty("input_neutral",neutral);out.addProperty("unknown_outcome",unknown||budget.unknown()||!neutral);
        out.addProperty("automatic_replay_allowed",false);out.addProperty("server_confirmed",false);return out;
    }
    static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason==null?"target_scope_guard_failed":reason);}
}
