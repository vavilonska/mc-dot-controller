package probe;
import java.util.*;
import org.spongepowered.asm.service.*;
public final class OfflineProperties implements IGlobalPropertyService {
 private record Key(String value) implements IPropertyKey {}
 private final Map<IPropertyKey,Object> values=new HashMap<>();
 public IPropertyKey resolveKey(String n){return new Key(n);}
 @SuppressWarnings("unchecked") public <T>T getProperty(IPropertyKey k){return (T)values.get(k);}
 public void setProperty(IPropertyKey k,Object v){values.put(k,v);}
 public <T>T getProperty(IPropertyKey k,T d){T v=getProperty(k);return v==null?d:v;}
 public String getPropertyString(IPropertyKey k,String d){Object v=values.get(k);return v==null?d:v.toString();}
}
