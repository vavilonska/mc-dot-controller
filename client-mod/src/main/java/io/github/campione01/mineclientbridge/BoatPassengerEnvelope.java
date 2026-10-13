package io.github.campione01.mineclientbridge;

/** Validates native rider geometry against the prism actually read by BoatCorridor. */
final class BoatPassengerEnvelope {
    // Coordinate arithmetic only, not a seat/motion tolerance. Mount geometry comes
    // from Entity.getPassengerRidingPosition minus the passenger VEHICLE attachment.
    static final double NUMERIC_EPSILON = 1e-5;
    static final double MAX_WIDTH = 1.4;
    static final double MAX_HEIGHT = 2.9;
    static final double MAX_RADIUS = 2.0; // Leaves room for the tick corridor's +1 margin.
    static final double VERTICAL_MARGIN = .1;
    record Result(String reason,double radius) { boolean accepted() { return reason==null; } }

    static Result inspect(BoatCollision.Box actual,BoatCollision.Box nativeExpected,
                          double boatX,double boatZ,int surfaceY) {
        if(!valid(actual)||!valid(nativeExpected)||!Double.isFinite(boatX)||!Double.isFinite(boatZ))
            return rejected("passenger_geometry_unknown");
        double width=actual.maxX()-actual.minX(),depth=actual.maxZ()-actual.minZ(),height=actual.maxY()-actual.minY();
        if(width>MAX_WIDTH||depth>MAX_WIDTH||height>MAX_HEIGHT)
            return rejected("unsupported_passenger_dimensions");
        if(!same(actual.minX(),nativeExpected.minX())||!same(actual.minY(),nativeExpected.minY())
                ||!same(actual.minZ(),nativeExpected.minZ())||!same(actual.maxX(),nativeExpected.maxX())
                ||!same(actual.maxY(),nativeExpected.maxY())||!same(actual.maxZ(),nativeExpected.maxZ()))
            return rejected("passenger_attachment_mismatch");
        // BoatCorridor inspects [surface-2,surface+3). The old surface-.8 floor
        // belongs to BOAT buoyancy, not passenger feet, which sit below the hull.
        if(actual.minY()<surfaceY-2+VERTICAL_MARGIN||actual.maxY()>surfaceY+3-VERTICAL_MARGIN)
            return rejected("unsupported_passenger_dimensions");
        double offset=Math.hypot((actual.minX()+actual.maxX())/2-boatX,
                (actual.minZ()+actual.maxZ())/2-boatZ);
        // Circumscribed square covers every rotation of a seated passenger and its
        // axis-aligned body, including an offset second seat and turns in place.
        double radius=offset+Math.hypot(width/2,depth/2);
        if(!Double.isFinite(radius)||radius>MAX_RADIUS)
            return rejected("unsupported_passenger_dimensions");
        return new Result(null,radius);
    }
    static String attachment(double x,double y,double z) {
        if(!Double.isFinite(x)||!Double.isFinite(y)||!Double.isFinite(z))return "passenger_geometry_unknown";
        // Passenger yaw may differ from boat yaw. Nonvertical custom attachments
        // could cancel the seat offset now but extend farther on a later turn.
        if(Math.abs(x)>NUMERIC_EPSILON||Math.abs(z)>NUMERIC_EPSILON)return "unsupported_passenger_attachment";
        return null;
    }
    static String membership(int count,long uniqueCount,boolean direct,boolean alive,boolean spectator,int nestedCount) {
        return count<1||count>2||uniqueCount!=count||!direct||!alive||spectator||nestedCount!=0
                ? "unsupported_passengers" : null;
    }
    static boolean valid(BoatCollision.Box b) {
        return b!=null&&b.finite()&&b.minX()<b.maxX()&&b.minY()<b.maxY()&&b.minZ()<b.maxZ();
    }
    private static boolean same(double a,double b) {return Math.abs(a-b)<=NUMERIC_EPSILON;}
    private static Result rejected(String reason) {return new Result(reason,Double.NaN);}
    private BoatPassengerEnvelope() { }
}
