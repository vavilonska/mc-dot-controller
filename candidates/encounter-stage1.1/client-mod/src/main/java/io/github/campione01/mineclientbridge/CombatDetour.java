package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.LongSupplier;

/**
 * Pure, deliberately incomplete local detours. One instance belongs to one combat action.
 * Planning never authorizes movement: the adapter must recheck the live swept corridor
 * and complete threat neighborhood before each ordinary input sample.
 */
final class CombatDetour {
    static final int MAX_ATTEMPTS = 3;
    static final int MAX_INTERMEDIATE_WAYPOINTS = 2;
    static final int MAX_CANDIDATES = 32;
    static final int MAX_GOALS = 8;
    static final int MAX_ROUTE_CANDIDATES = 512;
    static final int MAX_EDGE_CHECKS = 192;
    static final long MAX_PLAN_NANOS = 8_000_000L;
    static final double MAX_RADIUS = 3.0;
    static final double MAX_EDGE = 2.0;
    static final double MAX_GOAL_DISTANCE = 2.75;
    static final double MIN_TARGET_SEPARATION = 1.3;
    private static final double MIN_PROGRESS = .4;
    private static final double EPSILON = 1e-8;
    private static final double MAX_COORDINATE = 30_000_000;

    record Point(double x, double z) {
        boolean finite() {
            return Double.isFinite(x) && Double.isFinite(z)
                    && Math.abs(x) <= MAX_COORDINATE && Math.abs(z) <= MAX_COORDINATE;
        }
        double distance(Point other) { return Math.hypot(other.x-x, other.z-z); }
    }
    /** Clearance is a finite nonnegative minimum margin, or zero for binary admission. */
    record EdgeResult(boolean clear, double clearance, String reason) { }
    /**
     * Same grounded Y for both endpoints. The adapter checks every <=.65-block piece
     * using FlatStepCorridor's continuous square sweep, plus complete threat clearance.
     * Unknown, incomplete, hazardous, wet, unloaded, unsupported or colliding means deny.
     * Callbacks must themselves be bounded; Java cannot preempt an arbitrary callback.
     */
    @FunctionalInterface interface EdgeCheck { EdgeResult check(Point from, Point to); }
    /** Waypoints exclude start and include the final short toward-target goal. */
    record Plan(List<Point> waypoints, double score, double length, double clearance) {
        Plan { waypoints = List.copyOf(waypoints); }
    }
    record Result(Plan plan, String reason, int attempts, int candidateChecks, int edgeChecks) { }
    private static final class Edge {
        final Point from, to;
        Edge(Point from, Point to) { this.from=from; this.to=to; }
        @Override public int hashCode() {
            int h=Double.hashCode(from.x); h=31*h+Double.hashCode(from.z);
            h=31*h+Double.hashCode(to.x); return 31*h+Double.hashCode(to.z);
        }
        @Override public boolean equals(Object other) {
            return other instanceof Edge e && Double.compare(from.x,e.from.x)==0
                    && Double.compare(from.z,e.from.z)==0 && Double.compare(to.x,e.to.x)==0
                    && Double.compare(to.z,e.to.z)==0;
        }
    }
    private record Candidate(List<Point> points, double length, double rank) { }
    private record RankedPoint(Point point, double rank) { }
    private static final Comparator<Candidate> ROUTE_ORDER = new Comparator<>() {
        @Override public int compare(Candidate a, Candidate b) {
            int byRank=Double.compare(a.rank,b.rank);
            return byRank!=0 ? byRank : Integer.compare(a.points.size(),b.points.size());
        }
    };
    private static final Comparator<RankedPoint> POINT_ORDER = new Comparator<>() {
        @Override public int compare(RankedPoint a, RankedPoint b) {
            int byRank=Double.compare(a.rank,b.rank);
            if(byRank!=0) return byRank;
            int byX=Double.compare(a.point.x,b.point.x);
            return byX!=0 ? byX : Double.compare(a.point.z,b.point.z);
        }
    };

    private final LongSupplier clock;
    private int attempts;
    private Plan active;

    CombatDetour() { this(System::nanoTime); }
    CombatDetour(LongSupplier clock) { this.clock = Objects.requireNonNull(clock); }
    int attempts() { return attempts; }
    Plan activePlan() { return active; }
    /** Clearing, completion, loss of route and recovery never refund a planning attempt. */
    void clear() { active = null; }
    void rebaseAfterRecovery() { clear(); }

    Result plan(Point start, Point target, EdgeCheck check) {
        clear();
        if (attempts >= MAX_ATTEMPTS)
            return new Result(null, "detour_attempt_budget", attempts, 0, 0);
        attempts++;
        if (start == null || target == null || !start.finite() || !target.finite() || check == null)
            return new Result(null, "invalid_detour_request", attempts, 0, 0);
        double distance = start.distance(target);
        if (!Double.isFinite(distance) || distance < MIN_PROGRESS)
            return new Result(null, "detour_no_local_progress", attempts, 0, 0);
        Search search = new Search(check);
        double goalDistance = Math.min(MAX_GOAL_DISTANCE, Math.max(MIN_PROGRESS,distance-MIN_TARGET_SEPARATION));
        double ux = (target.x-start.x)/distance, uz = (target.z-start.z)/distance;
        Point goal = offset(start, ux, uz, goalDistance, 0);
        List<Point> points = candidates(start, goal, ux, uz);
        List<Point> goals = goals(start, target, goal, points);
        List<Candidate> routes = routes(start, target, goals, points, search);
        Plan best = null;
        int firstSafeCandidate = -1, firstSafeEdge = -1;
        for (Candidate route : routes) {
            // Once there is a complete route, spend at most a tiny bounded amount on
            // alternatives. A valid route must not require exhaustive world queries.
            if (best != null && (search.candidates-firstSafeCandidate >= 4 || search.edges-firstSafeEdge >= 8)) break;
            if (!search.withinTime()) break;
            if (search.candidates >= MAX_ROUTE_CANDIDATES) {
                search.stop = "detour_candidate_budget";
                break;
            }
            search.candidates++;
            Point from = start;
            double clearance = Double.MAX_VALUE;
            boolean clear = true;
            for (Point to : route.points) {
                EdgeResult edge = search.edge(from, to);
                if (edge == null || !edge.clear()) { clear = false; break; }
                clearance = Math.min(clearance, edge.clearance());
                from = to;
            }
            if (clear) {
                // Safety is a hard prerequisite. Among admitted routes, prefer clearance,
                // net target progress and economical motion, without closer-only waypoints.
                double progress = distance-route.points.getLast().distance(target);
                double score = 4*progress + 2*Math.min(4, clearance)
                        - route.length - .15*(route.points.size()-1);
                if (best == null) { firstSafeCandidate = search.candidates; firstSafeEdge = search.edges; }
                if (best == null || score > best.score()+EPSILON)
                    best = new Plan(route.points, score, route.length, clearance);
            }
            if (search.stop != null) break;
        }
        // A deadline reached between callbacks may retain an earlier complete route.
        // An overlong callback or invalid clock never grants movement permission.
        search.withinTime();
        if (search.callbackOverran || "invalid_detour_clock".equals(search.stop)) best = null;
        active = best;
        return new Result(best, best != null ? "detour_found"
                : search.stop != null ? search.stop : "detour_no_safe_route",
                attempts, search.candidates, search.edges);
    }

    private static List<Point> candidates(Point start, Point goal, double ux, double uz) {
        List<Point> all = new ArrayList<>();
        int bx = (int)Math.floor(start.x), bz = (int)Math.floor(start.z);
        // Absolute centers retain narrow safe passages hidden by target-relative sampling.
        for (int x=-3; x<=3; x++) for (int z=-3; z<=3; z++)
            add(all, start, goal, new Point(bx+x+.5, bz+z+.5));
        for (double forward : new double[]{0, .5, 1.5, 2})
            for (double side : new double[]{-1.5, -1, 1, 1.5})
                add(all, start, goal, offset(start, ux, uz, forward, side));
        List<RankedPoint> ranked = new ArrayList<>();
        for(Point p : all) ranked.add(new RankedPoint(p,start.distance(p)+p.distance(goal)));
        ranked.sort(POINT_ORDER);
        List<Point> limited = new ArrayList<>();
        for(int i=0;i<Math.min(MAX_CANDIDATES,ranked.size());i++) limited.add(ranked.get(i).point);
        return limited;
    }

    private static void add(List<Point> points, Point start, Point goal, Point p) {
        if (!p.finite() || start.distance(p) > MAX_RADIUS+EPSILON
                || start.distance(p) < EPSILON || goal.distance(p) < EPSILON) return;
        for (Point existing : points) if (existing.distance(p) < EPSILON) return;
        points.add(p);
    }

    private static List<Point> goals(Point start, Point target, Point primary, List<Point> points) {
        List<Point> goals = new ArrayList<>();
        if (goalAllowed(start,target,primary)) goals.add(primary);
        List<RankedPoint> alternatives = new ArrayList<>();
        for (Point point : points) if (goalAllowed(start,target,point))
            alternatives.add(new RankedPoint(point,point.distance(target)));
        alternatives.sort(POINT_ORDER);
        for (RankedPoint alternative : alternatives) {
            if (goals.size() >= MAX_GOALS) break;
            boolean duplicate=false;
            for(Point existing : goals) if(existing.distance(alternative.point)<EPSILON) { duplicate=true; break; }
            if (!duplicate) goals.add(alternative.point);
        }
        return goals;
    }

    private static boolean goalAllowed(Point start, Point target, Point point) {
        return point.finite() && start.distance(point) <= MAX_RADIUS+EPSILON
                && point.distance(target) >= MIN_TARGET_SEPARATION-EPSILON
                && start.distance(target)-point.distance(target) >= MIN_PROGRESS-EPSILON;
    }

    private static List<Candidate> routes(Point start, Point target, List<Point> goals, List<Point> points, Search search) {
        List<Candidate> routes = new ArrayList<>();
        int count=points.size();
        double[] fromStart=new double[count];
        double[][] between=new double[count][count];
        for(int i=0;i<count;i++) {
            if(!search.withinTime()) return List.of();
            fromStart[i]=start.distance(points.get(i));
            for(int j=0;j<count;j++) between[i][j]=points.get(i).distance(points.get(j));
        }
        for (Point goal : goals) {
            if(!search.withinTime()) return List.of();
            double goalRank=4*goal.distance(target);
            double direct=start.distance(goal);
            if(validStep(direct)) routes.add(new Candidate(List.of(goal),direct,direct+goalRank));
            double[] toGoal=new double[count];
            for(int i=0;i<count;i++) toGoal[i]=points.get(i).distance(goal);
            for (int i=0;i<count;i++) {
                if(!search.withinTime()) return List.of();
                if(!validStep(fromStart[i])) continue;
                Point first=points.get(i);
                if(validStep(toGoal[i])) {
                    double length=fromStart[i]+toGoal[i];
                    routes.add(new Candidate(List.of(first,goal),length,length+goalRank));
                }
                for (int j=0;j<count;j++) {
                    if(!validStep(between[i][j]) || !validStep(toGoal[j])) continue;
                    double length=fromStart[i]+between[i][j]+toGoal[j];
                    routes.add(new Candidate(List.of(first,points.get(j),goal),length,length+goalRank));
                }
            }
        }
        routes.sort(ROUTE_ORDER);
        // Generation is finite (<=8*(1+32+32*31)); expensive reads obey tighter caps.
        return routes;
    }

    private static boolean validStep(double step) { return step >= EPSILON && step <= MAX_EDGE+EPSILON; }

    private static Point offset(Point origin, double ux, double uz, double forward, double side) {
        return new Point(origin.x+ux*forward-uz*side, origin.z+uz*forward+ux*side);
    }

    private final class Search {
        final EdgeCheck check;
        final long started;
        long last;
        final Map<Edge, EdgeResult> cache = new HashMap<>();
        int candidates, edges;
        String stop;
        boolean callbackOverran;
        Search(EdgeCheck check) { this.check = check; started = last = clock.getAsLong(); }
        boolean withinTime() {
            if ("detour_time_budget".equals(stop) || "invalid_detour_clock".equals(stop)) return false;
            long now = clock.getAsLong();
            long elapsed = now-started;
            if (now-last < 0 || elapsed < 0) { stop = "invalid_detour_clock"; return false; }
            last = now;
            if (elapsed >= MAX_PLAN_NANOS) { stop = "detour_time_budget"; return false; }
            return true;
        }
        EdgeResult edge(Point from, Point to) {
            if (!withinTime()) return null;
            Edge key = new Edge(from, to);
            EdgeResult known = cache.get(key);
            if (known != null) return known;
            if (edges >= MAX_EDGE_CHECKS) { stop = "detour_edge_budget"; return null; }
            edges++;
            EdgeResult result;
            try { result = check.check(from, to); }
            catch (RuntimeException exception) { result = new EdgeResult(false, 0, "edge_check_failed"); }
            if (!withinTime()) { callbackOverran = true; return null; }
            if (result == null || !Double.isFinite(result.clearance()) || result.clearance() < 0)
                result = new EdgeResult(false, 0, "invalid_edge_evidence");
            cache.put(key, result);
            return result;
        }
    }
}
