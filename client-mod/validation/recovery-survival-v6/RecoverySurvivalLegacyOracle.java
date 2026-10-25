package io.github.campione01.mineclientbridge;
import java.nio.file.*;
/** Compiles/runs against predecessor and candidate independently, no game initialization. */
public final class RecoverySurvivalLegacyOracle {
 public static void main(String[] args)throws Exception{
  Path original=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);Path file=out.resolve("journal.bin");Files.copy(original,file);
  try(var store=new RecoveryShortInputLedger.FileStore(file,true)){
   var rows=store.read();store.write(rows);if(!java.util.Arrays.equals(Files.readAllBytes(original),Files.readAllBytes(file)))throw new AssertionError("oldbytes");
   var ledger=new RecoveryShortInputLedger(store,()->1,true,true);var f=NativeRecoveryShortInput.class.getDeclaredField("ledger");f.setAccessible(true);f.set(null,ledger);
   try(var stream=Files.newOutputStream(out.resolve("receipts.jsonl"))){for(var e:rows){stream.write(RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));stream.write('\n');}}
   System.out.println("Legacy actual receipts/requests digest original "+rows.size());
  }
 }
}
