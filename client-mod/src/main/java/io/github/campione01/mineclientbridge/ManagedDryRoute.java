package io.github.campione01.mineclientbridge;

import java.io.InputStream;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

/** Closed, pinned field readers for the actual current Baritone movement, not the next path. */
final class ManagedDryRoute {
    private static final Map<String,String> PINS=Map.ofEntries(
        Map.entry("baritone.i","4c5eb96811ffbb51533c5a072afb8302525949058be26be2174ddae8870e9a8c"),
        Map.entry("baritone.dm","d64de18ae424809c8c4bf86b7891cf7d34f24d502e26e28ae0a253c577b1554c"),
        Map.entry("baritone.cb","f3e7780cbd040ec8846165a67abc7cd8026f17930780adc831cfd1628cf835a2"),
        Map.entry("baritone.dj","206161498b61b7e8afaa41c5f1f5e9e4e7b6583f318e572df3b9ec89916a3303"),
        Map.entry("baritone.dc","6a4e90adc973b26cb4f18c739b9237b20d37212e11a0e48b83a3318b19785dda"),
        Map.entry("baritone.dd","591746804df46066a9cfb3c13c1de84c02f30c20bdb83cbe719c583d7f3d3823"),
        Map.entry("baritone.de","a00aa1d75c635631a393e7f137db0c74bd8e12b63a614e98016916ce4d546000"),
        Map.entry("baritone.bx","660e0f797aeea69c8dd7f60f7b531b7f4fb29cc90649f06f20e0b7c7b4c04b9f"),
        Map.entry("baritone.dl","18f3159f37fa2ede8c9fc5c1b78ab72f6eb3c873afe324fb172b9391ca565e4f"),
        Map.entry("baritone.dn","25d8e08156a026a57feebcfc4f93e559862a4272252050f50955a3b3aa8804da"),
        Map.entry("baritone.api.utils.BetterBlockPos","17e515351e003ee180fcbdf57f5ef209edb306abe031e95543c9883b88f4523f"),
        Map.entry("com.google.common.collect.Lists$ReverseList","2fe55e018e1c4364ec035e30871a0cc73f8fc97e747bfdb9fe8c1aa2d49178c5"),
        Map.entry("com.google.common.collect.Lists$RandomAccessReverseList","17f841c5377bb83f5f2e57dc9860c1741602391fc4bdbbbf6fe6757b6251d6fa"));
    private static final ClassLoader LOADER=ManagedDryRoute.class.getClassLoader();
    private static boolean verified;
    record Snapshot(Object owner,Object executor,Object path,Object movement,Object positions,Object movements,
                    int index,int length,ManagedDryStepPolicy.Step step) {
        boolean same(Snapshot b){return b!=null&&owner==b.owner&&executor==b.executor&&path==b.path
            &&movement==b.movement&&positions==b.positions&&movements==b.movements&&index==b.index&&length==b.length
            &&java.util.Objects.equals(step,b.step);}
    }
    static synchronized void verify() throws Exception {
        if(verified)return;
        for(var pin:PINS.entrySet())try(InputStream stream=LOADER.getResourceAsStream(pin.getKey().replace('.','/')+".class")){
            require(stream!=null,"managed_navigation_route_bytes_missing");byte[] bytes=stream.readNBytes(1_048_577);
            require(bytes.length<=1_048_576&&HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(pin.getValue()),"managed_navigation_route_bytes_changed");
        }
        verified=true;
    }
    static Snapshot read(Object owner) throws Exception {
        require(verified,"managed_navigation_route_reader_not_initialized");exact(owner,"baritone.i");
        Object executor=value(owner,"a",type("baritone.dm"));
        if(executor==null)return new Snapshot(owner,null,null,null,null,null,-1,0,null);
        exact(executor,"baritone.dm");int index=(int)value(executor,"a",int.class);
        Object path=value(executor,"a",type("baritone.api.pathing.calc.IPath"));
        require(path==null||path.getClass()!=type("baritone.dl"),"managed_navigation_cutoff_path_reader_unsupported");
        require(path!=null&&List.of(type("baritone.bx"),type("baritone.dn")).contains(path.getClass()),"managed_navigation_path_class_unproven");
        if(path.getClass()==type("baritone.bx"))require((boolean)value(path,"a",boolean.class),"managed_navigation_path_not_verified");
        Object ps=value(path,"a",List.class),ms=value(path,"b",List.class);
        // bx stores a Guava reverse view of an ArrayList; dn's splice factory stores ArrayLists.
        // Read the pinned Guava field directly. Never invoke reverse-view or JDK-wrapper methods.
        ArrayView positions=positions(path,ps);ArrayList<?> movements=array(ms);int count=movements.size();
        require(count>=0&&count<=4096&&positions.size()==count+1&&index>=0&&index<=count,"managed_navigation_path_index_unproven");
        if(index==count)return new Snapshot(owner,executor,path,null,ps,ms,index,count,null);
        Object movement=movements.get(index);ManagedDryStepPolicy.Kind kind;
        require(movement!=null,"managed_navigation_movement_missing");
        if(movement.getClass()==type("baritone.dj"))kind=ManagedDryStepPolicy.Kind.TRAVERSE;
        else if(movement.getClass()==type("baritone.dc"))kind=ManagedDryStepPolicy.Kind.ASCEND;
        else if(movement.getClass()==type("baritone.dd"))kind=ManagedDryStepPolicy.Kind.DESCEND;
        else if(movement.getClass()==type("baritone.de"))kind=ManagedDryStepPolicy.Kind.DIAGONAL;
        else throw new IllegalStateException("managed_navigation_nonordinary_step_refused");
        Object src=value(type("baritone.cb"),movement,"a",type("baritone.api.utils.BetterBlockPos"));
        Object dst=value(type("baritone.cb"),movement,"b",type("baritone.api.utils.BetterBlockPos"));
        var a=point(src);var b=point(dst);
        require(a.equals(point(positions.get(index)))&&b.equals(point(positions.get(index+1))),"managed_navigation_step_path_mismatch");
        return new Snapshot(owner,executor,path,movement,ps,ms,index,count,new ManagedDryStepPolicy.Step(kind,a,b));
    }
    private record ArrayView(ArrayList<?> backing,boolean reversed) {
        int size(){return backing.size();}
        Object get(int index){return backing.get(reversed?backing.size()-1-index:index);}
    }
    private static ArrayView positions(Object path,Object raw)throws Exception{
        if(path.getClass()==type("baritone.dn"))return new ArrayView(array(raw),false);
        exact(raw,"com.google.common.collect.Lists$RandomAccessReverseList");
        Class<?> declaring=type("com.google.common.collect.Lists$ReverseList");
        require(raw.getClass().getSuperclass()==declaring,"managed_navigation_reverse_list_class_unproven");
        Object forward=value(declaring,raw,"forwardList",List.class);
        return new ArrayView(array(forward),true);
    }
    private static ArrayList<?> array(Object raw){
        require(raw!=null&&raw.getClass()==ArrayList.class,"managed_navigation_path_list_unproven");
        return (ArrayList<?>)raw;
    }
    private static ManagedDryStepPolicy.Point point(Object p)throws Exception{
        exact(p,"baritone.api.utils.BetterBlockPos");return new ManagedDryStepPolicy.Point((int)value(p,"x",int.class),(int)value(p,"y",int.class),(int)value(p,"z",int.class));
    }
    private static Object value(Object object,String name,Class<?> type)throws Exception{return value(object.getClass(),object,name,type);}
    private static Object value(Class<?> owner,Object object,String name,Class<?> type)throws Exception{
        for(Field f:owner.getDeclaredFields())if(f.getName().equals(name)&&f.getType()==type){
            require(!java.lang.reflect.Modifier.isStatic(f.getModifiers())&&f.trySetAccessible(),"managed_navigation_route_field_unavailable");return f.get(object);
        }
        throw new IllegalStateException("managed_navigation_route_field_changed");
    }
    private static Class<?> type(String name)throws ClassNotFoundException{return Class.forName(name,false,LOADER);}
    private static void exact(Object object,String name)throws Exception{require(object!=null&&object.getClass()==type(name),"managed_navigation_route_receiver_changed");}
    private static void require(boolean ok,String why){if(!ok)throw new IllegalStateException(why);}
    private ManagedDryRoute(){}
}
