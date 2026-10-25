package io.github.campione01.mineclientbridge;
/** Immutable primitive/reference boundary; never dispatches an object's equals/hashCode. */
final class TypedBoundaryPolicy {
    private final Object[] identities;private final long[] scalars;
    TypedBoundaryPolicy(Object[] identities,long[] scalars){this.identities=identities.clone();this.scalars=scalars.clone();}
    boolean same(TypedBoundaryPolicy now){
        if(now==null||identities.length!=now.identities.length||scalars.length!=now.scalars.length)return false;
        for(int i=0;i<identities.length;i++)if(identities[i]!=now.identities[i])return false;
        for(int i=0;i<scalars.length;i++)if(scalars[i]!=now.scalars[i])return false;
        return true;
    }
}
