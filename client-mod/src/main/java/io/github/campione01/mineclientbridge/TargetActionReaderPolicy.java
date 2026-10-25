package io.github.campione01.mineclientbridge;

/** Reflection only: validates a getter's implementation without invoking it. */
final class TargetActionReaderPolicy {
    static boolean declaredBy(Class<?> actual,String name,Class<?> expected,Class<?>... arguments){
        try{return actual.getMethod(name,arguments).getDeclaringClass()==expected;}
        catch(ReflectiveOperationException unavailable){return false;}
    }
    static boolean implementationDeclaredBy(Class<?> actual,String name,Class<?> expected,Class<?>... arguments){
        for(Class<?> at=actual;at!=null;at=at.getSuperclass()){
            try{return at.getDeclaredMethod(name,arguments).getDeclaringClass()==expected;}
            catch(NoSuchMethodException inherited){}catch(SecurityException unavailable){return false;}
        }
        return false;
    }
    static boolean sameIdentityValues(java.util.List<?> before,java.util.List<?> after){
        if(before.size()!=after.size())return false;
        for(int i=0;i<before.size();i++)if(before.get(i)!=after.get(i))return false;
        return true;
    }
    /** Official exact Shulker returns Vec3.ZERO; its subclasses do not inherit this admission. */
    static boolean entityVelocityReader(Class<?> actual){
        Class<?> owner=actual==net.minecraft.world.entity.monster.Shulker.class
            ?net.minecraft.world.entity.monster.Shulker.class:net.minecraft.world.entity.Entity.class;
        return declaredBy(actual,"getDeltaMovement",owner);
    }
    private TargetActionReaderPolicy(){}
}
