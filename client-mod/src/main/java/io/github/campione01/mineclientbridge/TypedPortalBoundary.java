package io.github.campione01.mineclientbridge;
import java.util.ArrayList;
import java.util.List;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
/** Pure-data snapshot around the final callback-backed external-controller query. */
final class TypedPortalBoundary {
    private final TypedBoundaryPolicy frame;
    private final LocalPlayer player;private final ClientLevel level;
    private final net.minecraft.world.inventory.AbstractContainerMenu menu;
    private final List<BlockPos> positions;private final List<BlockState> states=new ArrayList<>();
    private final List<Object> blockEntities=new ArrayList<>();
    private final List<TypedPortalStack> inventory=new ArrayList<>(),slotStacks=new ArrayList<>();
    private final List<Slot> slots;private final TypedPortalStack carried;
    private final int selected,revision,food;private final float health,saturation,yaw,pitch;
    private final double x,y,z,vx,vy,vz;private final AABB box;
    TypedPortalBoundary(LocalPlayer p,ClientLevel l,List<BlockPos> cells){
        player=p;level=l;positions=List.copyOf(cells);menu=p.containerMenu;
        require(menu==p.inventoryMenu&&menu.getClass()==InventoryMenu.class,"typed_boundary_menu_changed");
        selected=p.getInventory().selected;revision=menu.getStateId();carried=new TypedPortalStack(menu.getCarried());
        for(int i=0;i<41;i++)inventory.add(new TypedPortalStack(p.getInventory().getItem(i)));
        slots=List.copyOf(menu.slots);for(Slot slot:slots){vanillaSlot(slot);slotStacks.add(new TypedPortalStack(slot.container.getItem(slot.getContainerSlot())));}
        for(BlockPos pos:positions){require(l.hasChunkAt(pos),"typed_boundary_unloaded");states.add(TypedPortalReaders.block(l,pos));blockEntities.add(TypedPortalReaders.blockEntity(l,pos));}
        x=p.getX();y=p.getY();z=p.getZ();var v=p.getDeltaMovement();vx=v.x;vy=v.y;vz=v.z;box=p.getBoundingBox();
        yaw=p.getYRot();pitch=p.getXRot();health=p.getHealth();food=p.getFoodData().getFoodLevel();saturation=p.getFoodData().getSaturationLevel();frame=frame();
    }
    void unchanged(){
        require(frame.same(frame()),"typed_boundary_raw_changed_after_callback");
        require(player.containerMenu==menu&&player.inventoryMenu==menu&&player.getInventory().selected==selected&&menu.getStateId()==revision
            &&carried.same(menu.getCarried())&&menu.slots.size()==slots.size(),"typed_boundary_inventory_context_changed");
        for(int i=0;i<41;i++)require(inventory.get(i).same(player.getInventory().getItem(i)),"typed_boundary_inventory_changed");
        for(int i=0;i<slots.size();i++){Slot slot=menu.slots.get(i);require(slot==slots.get(i),"typed_boundary_slot_changed");vanillaSlot(slot);require(slotStacks.get(i).same(slot.container.getItem(slot.getContainerSlot())),"typed_boundary_slot_item_changed");}
        for(int i=0;i<positions.size();i++){BlockPos pos=positions.get(i);require(level.hasChunkAt(pos)&&TypedPortalReaders.block(level,pos)==states.get(i)&&TypedPortalReaders.blockEntity(level,pos)==blockEntities.get(i),"typed_boundary_footprint_changed");}
        var v=player.getDeltaMovement();var b=player.getBoundingBox();
        require(player.getX()==x&&player.getY()==y&&player.getZ()==z&&v.x==vx&&v.y==vy&&v.z==vz
            &&b.minX==box.minX&&b.minY==box.minY&&b.minZ==box.minZ&&b.maxX==box.maxX&&b.maxY==box.maxY&&b.maxZ==box.maxZ
            &&player.getYRot()==yaw&&player.getXRot()==pitch&&player.getHealth()==health&&player.getFoodData().getFoodLevel()==food
            &&player.getFoodData().getSaturationLevel()==saturation,"typed_boundary_pose_changed");
    }
    private TypedBoundaryPolicy frame(){
        var identities=new ArrayList<Object>();var numbers=new ArrayList<Long>();
        identities.add(player);identities.add(level);identities.add(player.containerMenu);identities.add(menu.getCarried());
        for(Slot slot:menu.slots){vanillaSlot(slot);identities.add(slot);identities.add(slot.container);identities.add(slot.container.getItem(slot.getContainerSlot()));}
        for(BlockPos pos:positions){identities.add(TypedPortalReaders.block(level,pos));identities.add(TypedPortalReaders.blockEntity(level,pos));}
        for(int i=0;i<41;i++){var stack=player.getInventory().getItem(i);identities.add(stack);identities.add(stack.getItem());numbers.add((long)stack.getCount());}
        numbers.add((long)player.getInventory().selected);numbers.add((long)menu.getStateId());
        var v=player.getDeltaMovement();var b=player.getBoundingBox();
        for(double value:new double[]{player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ,
            player.getYRot(),player.getXRot(),player.getHealth(),player.getFoodData().getFoodLevel(),player.getFoodData().getSaturationLevel()})numbers.add(Double.doubleToLongBits(value));
        return new TypedBoundaryPolicy(identities.toArray(),numbers.stream().mapToLong(Long::longValue).toArray());
    }
    private static void vanillaSlot(Slot s){
        Class<?> t=s.getClass(),c=s.container.getClass();
        require((t==Slot.class||t==net.minecraft.world.inventory.ResultSlot.class||t.getClassLoader()==Slot.class.getClassLoader()
            &&(t.getName().equals("net.minecraft.world.inventory.ArmorSlot")||t.getName().equals("net.minecraft.world.inventory.InventoryMenu$1")))
            &&(c==net.minecraft.world.entity.player.Inventory.class||c==net.minecraft.world.inventory.TransientCraftingContainer.class||c==net.minecraft.world.inventory.ResultContainer.class),"typed_boundary_slot_reader_unknown");
    }
    private static void require(boolean ok,String reason){if(!ok)throw new IllegalStateException(reason);}
}
