package io.github.campione01.mineclientbridge;
import java.util.IdentityHashMap;
/** Never calls a component/type's equals or hashCode. Equal-but-replaced values fail closed. */
final class IdentityComponentSnapshot {
    private final IdentityHashMap<Object,Object> values=new IdentityHashMap<>();
    void add(Object type,Object value){if(type==null||value==null||values.containsKey(type))throw new IllegalStateException("typed_component_identity_duplicate");values.put(type,value);}
    boolean same(IdentityComponentSnapshot other,Object ignoredType){
        if(other==null)return false;int expected=values.size()-(values.containsKey(ignoredType)?1:0),actual=other.values.size()-(other.values.containsKey(ignoredType)?1:0);
        if(expected!=actual)return false;
        for(var row:values.entrySet())if(row.getKey()!=ignoredType&&other.values.get(row.getKey())!=row.getValue())return false;
        return true;
    }
}
