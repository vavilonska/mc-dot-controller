package net.minecraft.world.item;
public class BlockItem extends Item {
 private final Object block;
 public BlockItem(String id,Object block){super(id);this.block=block;}
 public Object getBlock(){return block;}
}
