package net.minecraft.world.phys.shapes;
import net.minecraft.client.Minecraft;
public class CollisionContext { public final Minecraft.Player player; private CollisionContext(Minecraft.Player p){player=p;} public static CollisionContext of(Minecraft.Player p){return new CollisionContext(p);} }
