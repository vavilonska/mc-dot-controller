package io.github.campione01.mineclientbridge;
/** Conservative broad-phase moving-entity protection, testable without a game. */
final class BoatCollision {
 record Box(double minX,double minY,double minZ,double maxX,double maxY,double maxZ) {
  boolean finite() {return Double.isFinite(minX)&&Double.isFinite(minY)&&Double.isFinite(minZ)&&Double.isFinite(maxX)&&Double.isFinite(maxY)&&Double.isFinite(maxZ)&&minX<=maxX&&minY<=maxY&&minZ<=maxZ;}
  Box sweep(double dx,double dy,double dz,double padding) {return new Box(minX+Math.min(0,dx)-padding,minY+Math.min(0,dy)-padding,minZ+Math.min(0,dz)-padding,maxX+Math.max(0,dx)+padding,maxY+Math.max(0,dy)+padding,maxZ+Math.max(0,dz)+padding);}
  boolean overlaps(Box b) {return maxX>=b.minX&&minX<=b.maxX&&maxY>=b.minY&&minY<=b.maxY&&maxZ>=b.minZ&&minZ<=b.maxZ;}
 }
 static boolean protectedOverlap(Box hull,double dx,double dz,Box entity,double vx,double vy,double vz) {
  if(hull==null||entity==null||!hull.finite()||!entity.finite()||!Double.isFinite(dx)||!Double.isFinite(dz))return true;
  if(!Double.isFinite(vx)||!Double.isFinite(vy)||!Double.isFinite(vz)||Math.hypot(vx,vz)>1||Math.abs(vy)>1)return true;
  return hull.sweep(dx,0,dz,1.2).overlaps(entity.sweep(vx*20,vy*20,vz*20,.5));
 }
 static double distanceToSegment(double x,double z,BoatSteering.Point a,BoatSteering.Point b) {
  double dx=b.x()-a.x(),dz=b.z()-a.z(),length=dx*dx+dz*dz;
  double t=length<1e-9?0:Math.max(0,Math.min(1,((x-a.x())*dx+(z-a.z())*dz)/length));
  return Math.hypot(x-a.x()-t*dx,z-a.z()-t*dz);
 }
 private BoatCollision() { }
}
