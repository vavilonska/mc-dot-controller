package io.github.campione01.mineclientbridge;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.UUID;

/** Read-only process-local identity for actual player objects, never player UUIDs.
 * Minecraft-thread only. Weak identity entries do not retain old worlds, invoke
 * user equals/hashCode, or give a returning original object a new generation. */
final class PlayerGeneration {
    private record Entry(WeakReference<Object> player, String token) { }
    private static final ArrayList<Entry> entries = new ArrayList<>();
    private PlayerGeneration() { }
    static String current(Object player) {
        if (player == null) return null;
        for (int i=entries.size()-1;i>=0;i--) {
            Entry entry=entries.get(i); Object prior=entry.player.get();
            if (prior==null) entries.remove(i);
            else if (prior==player) return entry.token;
        }
        if (entries.size()>=1024) throw new IllegalStateException("player_generation_capacity");
        String token=UUID.randomUUID().toString();
        entries.add(new Entry(new WeakReference<>(player),token));
        return token;
    }
    /** Pure actual-instance fence shared by the exporter and adversarial tests. */
    static boolean frameCurrent(Object player,Object currentPlayer,Object level,Object currentLevel,Object playerLevel,
            Object server,Object currentServer,Object data,Object currentData,Object uuid,Object currentUuid) {
        return player!=null&&player==currentPlayer&&level!=null&&level==currentLevel&&level==playerLevel
                &&server==currentServer&&data!=null&&data==currentData&&uuid!=null&&uuid==currentUuid;
    }
    static boolean matches(Object player,String token) {
        if(player==null||token==null)return false;
        for(Entry entry:entries)if(entry.player.get()==player)return token.equals(entry.token);
        return false;
    }
}
