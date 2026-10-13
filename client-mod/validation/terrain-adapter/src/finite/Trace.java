package finite;
import java.util.*;
public final class Trace {
 public static final List<String> events=new ArrayList<>();
 public static final Set<String> failures=new HashSet<>();
 public static void hit(String value) { events.add(value); if(failures.contains(value)) throw new IllegalStateException("fixture:"+value); }
 public static void reset(){events.clear();failures.clear();}
}
