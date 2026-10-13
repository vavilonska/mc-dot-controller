package net.minecraft.world.level.block.state.properties;
import finite.Trace;
public class Property<T extends Comparable<T>> {
 public final String label; public String name,value; public boolean nullValue;
 public Property(String name,String value){this.label=name==null?"null":name;this.name=name;this.value=value;}
 public String getName(){Trace.hit("property.name:"+label);return name;}
 public String getName(T input){Trace.hit("property.value:"+label);return nullValue?null:value;}
}
