package net.minecraft.client;
import net.minecraft.client.multiplayer.ClientLevel; import net.minecraft.core.BlockPos;
public class Minecraft { public static Minecraft instance; public ClientLevel level; public Player player; public boolean sameThread=true;
 public static Minecraft getInstance(){return instance;} public boolean isSameThread(){return sameThread;}
 public static final class Player { public double x=.5,y=64,z=.5; public boolean grounded=true; public float yaw;
 public double getX(){return x;} public double getY(){return y;} public double getZ(){return z;} public boolean onGround(){return grounded;} public float getYRot(){return yaw;}
 public BlockPos blockPosition(){return new BlockPos((int)Math.floor(x),(int)Math.floor(y),(int)Math.floor(z));}
 }
}
