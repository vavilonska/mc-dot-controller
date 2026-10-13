package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;
import java.util.function.LongSupplier;

/** Per-invocation, bounded primitive observations. Never grants movement or resets the deadline. */
final class CombatRetreatDiagnostics {
    record Window(int candidate,int window,long elapsedNanos,boolean returned,boolean resultPresent,Boolean clear,String reason,
                  FlatStepCorridor.CellRef rejectedCell) { }
    record Candidate(int candidate,int windows,long elapsedNanos,boolean clear,String reason,boolean budgetExhausted) { }
    private final LongSupplier clock;
    private final long started;
    private long previous,elapsedNanos,preFirstWindowElapsedNanos=-1,lastWindowElapsedNanos=-1,totalWindowElapsedNanos;
    private long candidateStarted,windowStarted;
    private int candidateIndex,windowIndex;
    private boolean clockInvalid,budgetExhausted;
    private String budgetCheckStage="none",lastBudgetCheckStage="initial";
    private final List<Candidate> candidates;
    private final List<Window> windows;

    CombatRetreatDiagnostics(LongSupplier clock) {
        this.clock=clock;
        long initial=0;
        try { initial=clock.getAsLong(); } catch(RuntimeException exception) { clockInvalid=true; }
        started=previous=initial;
        candidates=new ArrayList<>(CombatRetreatPolicy.MAX_CANDIDATES);
        windows=new ArrayList<>(CombatRetreatPolicy.MAX_CANDIDATES*CombatRetreatPolicy.MAX_WINDOWS);
    }
    private long sample() {
        long now=previous;
        try { now=clock.getAsLong(); } catch(RuntimeException exception) { clockInvalid=true; }
        long elapsed=now-started;
        if(now-previous<0 || elapsed<0) clockInvalid=true;
        if(!clockInvalid) { elapsedNanos=elapsed;previous=now; }
        return elapsedNanos;
    }
    boolean checkBudget(String stage) {
        lastBudgetCheckStage=stage;
        sample();
        if(clockInvalid || elapsedNanos>=CombatRetreatPolicy.MAX_CHECK_NANOS) {
            if(!budgetExhausted) budgetCheckStage=stage;
            budgetExhausted=true;
        }
        return budgetExhausted;
    }
    void beginCandidate(int index) { candidateIndex=index;candidateStarted=sample(); }
    void endCandidate(CombatRetreatPolicy.Validation result) {
        long elapsed=sample()-candidateStarted;
        if(candidates.size()<CombatRetreatPolicy.MAX_CANDIDATES)
            candidates.add(new Candidate(candidateIndex,result.windows(),elapsed,result.clear(),result.reason(),result.budgetExhausted()));
    }
    boolean beginWindow(int index) {
        if(checkBudget("pre_window_callback")) return false;
        windowIndex=index;windowStarted=elapsedNanos;
        if(preFirstWindowElapsedNanos<0) preFirstWindowElapsedNanos=windowStarted;
        return true;
    }
    void endWindow(CombatDetour.EdgeResult result,FlatStepCorridor.CellRef cell,boolean callbackReturned) {
        lastWindowElapsedNanos=sample()-windowStarted;
        totalWindowElapsedNanos+=lastWindowElapsedNanos;
        if(windows.size()<CombatRetreatPolicy.MAX_CANDIDATES*CombatRetreatPolicy.MAX_WINDOWS)
            windows.add(new Window(candidateIndex,windowIndex,lastWindowElapsedNanos,callbackReturned,callbackReturned && result!=null,
                    result==null?null:result.clear(),result==null?"retreat_window_unknown":result.reason(),cell));
    }
    long elapsedNanos() { return elapsedNanos; }
    long preFirstWindowElapsedNanos() { return preFirstWindowElapsedNanos; }
    long lastWindowElapsedNanos() { return lastWindowElapsedNanos; }
    long totalWindowElapsedNanos() { return totalWindowElapsedNanos; }
    boolean clockInvalid() { return clockInvalid; }
    String budgetCheckStage() { return budgetCheckStage; }
    String lastBudgetCheckStage() { return lastBudgetCheckStage; }
    List<Candidate> candidates() { return List.copyOf(candidates); }
    List<Window> windows() { return List.copyOf(windows); }
    Window lastWindow() { return windows.isEmpty()?null:windows.getLast(); }
}
