package io.github.campione01.mineclientbridge;

import java.util.UUID;
import java.util.Set;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Synthetic captured rows only. Never instantiates a game entity or level. */
final class WireV1Facts {
    static final Box PRISM=new Box(10,63,22,15,68,28);
    static Row far(int id,String type) {
        V p=new V(100.125+id,64.25,25.375),v=new V(1.0e-7,0,-2.5e-8);
        Box b=new Box(p.x()-.25,p.y(),p.z()-.25,p.x()+.25,p.y()+.75,p.z()+.25);
        boolean living=!Set.of("minecraft:boat","minecraft:chest_minecart","minecraft:item").contains(type);
        Flags flags=new Flags(living,true,false,false,false,false,false,false,0,0,null);
        return new Row(id,new UUID(0,id+1L).toString(),type,CLASSES.get(type),false,p,b,v,p,flags,project(b,p,v,p,160));
    }
    static Row removed(int id) {
        return new Row(id,new UUID(0,id+1L).toString(),"minecraft:arrow","net.minecraft.world.entity.projectile.Arrow",true,
                null,null,null,null,null,null);
    }
    private WireV1Facts() { }
}
