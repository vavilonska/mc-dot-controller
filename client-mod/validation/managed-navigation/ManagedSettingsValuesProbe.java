package io.github.campione01.mineclientbridge;
import java.util.List;
public final class ManagedSettingsValuesProbe {
    public static final class Cell {public Object value;Cell(Object v){value=v;}}
    static int checks;static void check(boolean b){checks++;if(!b)throw new AssertionError("settings check "+checks);}
    public static void main(String[] args)throws Exception{
        Object original=new Object(),installed=new Object();var a=new Cell(original);var b=new Cell(Boolean.TRUE);
        var field=Cell.class.getField("value");var journal=new ManagedSettingsValues(field,List.of(
            new ManagedSettingsValues.Value(a,original,installed),new ManagedSettingsValues.Value(b,Boolean.TRUE,Boolean.FALSE)));
        check(!journal.unchanged());journal.install();check(a.value==installed&&b.value==Boolean.FALSE);check(journal.unchanged());
        try{journal.install();throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        journal.restore();check(a.value==original&&b.value==Boolean.TRUE);check(!journal.unchanged());
        try{journal.restore();throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        a=new Cell(original);b=new Cell(Boolean.TRUE);journal=new ManagedSettingsValues(field,List.of(
            new ManagedSettingsValues.Value(a,original,installed),new ManagedSettingsValues.Value(b,Boolean.TRUE,Boolean.FALSE)));
        journal.install();Object user=new Object();b.value=user;check(!journal.unchanged());
        try{journal.restore();throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        check(a.value==installed&&b.value==user); // Full precheck: no earlier field was restored either.
        a=new Cell(original);b=new Cell(Boolean.TRUE);journal=new ManagedSettingsValues(field,List.of(
            new ManagedSettingsValues.Value(a,original,installed),new ManagedSettingsValues.Value(b,Boolean.TRUE,Boolean.FALSE)));
        b.value=user;try{journal.install();throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        check(a.value==original&&b.value==user);
        System.out.println("ManagedSettingsValuesProbe "+checks+" checks passed");
    }
}
