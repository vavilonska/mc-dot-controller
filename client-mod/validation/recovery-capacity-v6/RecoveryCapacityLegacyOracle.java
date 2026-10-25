package io.github.campione01.mineclientbridge;
import java.nio.file.*;
/** Same source independently compiled against C6 and C7, to avoid sharing the candidate codec. */
public final class RecoveryCapacityLegacyOracle {
 public static void main(String[] args)throws Exception{
  Path input=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);Path file=out.resolve("journal.bin");Files.copy(input,file);
  try(var store=new RecoveryShortInputLedger.FileStore(file,true)){
   var rows=store.read();if(rows.size()!=481)throw new AssertionError("actual F481 count");store.write(rows);
   if(!java.util.Arrays.equals(Files.readAllBytes(input),Files.readAllBytes(file)))throw new AssertionError("F481 exact codec bytes");
   var ledger=new RecoveryShortInputLedger(store,()->1,true,true);var field=NativeRecoveryShortInput.class.getDeclaredField("ledger");field.setAccessible(true);field.set(null,ledger);
   try(var stream=Files.newOutputStream(out.resolve("receipts.jsonl"));var digests=Files.newBufferedWriter(out.resolve("digests.txt"))){for(var e:rows){stream.write(RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));stream.write('\n');digests.write(e.request.id()+" "+e.request.digest()+"\n");}}
   System.out.println("F481 actual native receipt/digest oracle PASS "+rows.size());
  }
 }
}
