package io.github.campione01.mineclientbridge;
import java.nio.file.*;
import java.security.*;
import java.util.*;
/** Independently compiled against frozen C7 and C8; FileStore opens only an output-directory copy. */
public final class RecoveryCapacity4096Oracle {
 public static void main(String[] args)throws Exception{
  Path input=Path.of(args[0]),out=Path.of(args[1]);byte[] original=Files.readAllBytes(input);Files.createDirectories(out);Path copy=out.resolve("journal.bin");Files.write(copy,original);
  if(!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original)).equals("ecf7ef54ca895c7b17a665ce0c572fcc7ac9eb1c123591f42de107067e16cfc6"))throw new AssertionError("F996 pin");
  var mode=RecoveryShortInputLedger.CapacityMode.SURVIVAL_V6;
  try(var store=new RecoveryShortInputLedger.FileStore(copy,mode)){
   var rows=store.read();if(rows.size()!=996||!rows.stream().allMatch(RecoveryShortInputLedger.Entry::settled))throw new AssertionError("F996 count/known");store.write(rows);if(!Arrays.equals(original,Files.readAllBytes(copy)))throw new AssertionError("F996 exact bytes");
   var ledger=new RecoveryShortInputLedger(store,()->1,true,mode);var field=NativeRecoveryShortInput.class.getDeclaredField("ledger");field.setAccessible(true);field.set(null,ledger);
   try(var stream=Files.newOutputStream(out.resolve("receipts.jsonl"));var digests=Files.newBufferedWriter(out.resolve("digests.txt"))){for(var e:rows){stream.write(RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));stream.write('\n');digests.write(e.request.id()+" "+e.request.digest()+"\n");}}
  }
  if(!Arrays.equals(original,Files.readAllBytes(input)))throw new AssertionError("original modified");System.out.println("F996 independent native byte/receipt/digest oracle PASS 996");
 }
}
