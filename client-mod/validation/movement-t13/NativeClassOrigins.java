package io.github.campione01.mineclientbridge;
import java.nio.file.Path;
import java.nio.file.Files;
/** Loads metadata without initializing game or bridge classes. */
public final class NativeClassOrigins {
 public static void main(String[] args)throws Exception {
  Path expected=Path.of(args[0]).toRealPath();
  java.util.List<String> names;
  try(var paths=Files.walk(expected)) {
   names=paths.filter(path->path.toString().endsWith(".class"))
    .map(path->expected.relativize(path).toString().replace(java.io.File.separatorChar,'.').replaceFirst("\\.class$", "")).sorted().toList();
  }
  if(names.isEmpty())throw new AssertionError("No fresh production classes");
  for(String name:names) {
   Class<?> type=Class.forName(name,false,NativeClassOrigins.class.getClassLoader());
   Path actual=Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
   if(!actual.equals(expected))throw new AssertionError("Not the fresh production output: "+name);
   System.out.println("PASS fresh production origin "+name);
  }
 }
}
