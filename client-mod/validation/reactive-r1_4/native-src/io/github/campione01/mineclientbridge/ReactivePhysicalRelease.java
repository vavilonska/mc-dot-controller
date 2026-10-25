package io.github.campione01.mineclientbridge;

/** Immutable release evidence. Replacing a dead player never rewrites the original action. */
final class ReactivePhysicalRelease {
 enum Basis { NONE, SAME_PLAYER, RELEASED_DEAD_PLAYER_REPLACED }
 record Context(Object player,Object level,Object server,String session,String generation,String playerUuid) {
  boolean valid(){return player!=null&&level!=null&&server!=null&&session!=null&&generation!=null&&playerUuid!=null;}
  boolean sameWorld(Context other){return other!=null&&valid()&&other.valid()&&level==other.level&&server==other.server&&session.equals(other.session)&&generation.equals(other.generation)&&playerUuid.equals(other.playerUuid);}
 }
 final Object entry;final Context context;final long revision;final boolean physical;
 ReactivePhysicalRelease(Object entry,Context context,long revision,boolean physical){this.entry=entry;this.context=context;this.revision=revision;this.physical=physical;}
 Basis basis(Object latest,long currentRevision,Context current,boolean originalPlayerDead,boolean currentPlayerAlive){
  if(!physical||entry!=latest||revision!=currentRevision||context==null||!context.sameWorld(current))return Basis.NONE;
  if(context.player==current.player)return Basis.SAME_PLAYER;
  // Only an already-proven release can cross this lifecycle boundary. A new neutral player
  // cannot turn an unconfirmed old input into a release; live owner/dispatch/neutral fences
  // are still checked separately immediately before admitting any new protection.
  return originalPlayerDead&&currentPlayerAlive?Basis.RELEASED_DEAD_PLAYER_REPLACED:Basis.NONE;
 }
}
