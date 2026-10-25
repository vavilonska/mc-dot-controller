package io.github.campione01.mineclientbridge;
import java.util.Set;
/** A one-action finite transition binding; no clock renewal and no grant after uncertainty. */
final class PortalTransitionPolicy {
    record Bound(String action,String session,String player,String server,String sourceWorld,String sourceDimension,String destination,long revision,long sourceNano,long deadline){}
    record Live(String action,String session,String player,String server,String world,String dimension,long revision,long nano){}
    static boolean permits(Bound b,Live v,String reason,boolean owned,boolean attempted,boolean unknown,boolean sourceContact){
        return b!=null&&v!=null&&owned&&attempted&&!unknown&&sourceContact
            &&Set.of("world_changed","world_or_player_changed","world_transition","capability_world_changed","capability_dimension_changed","player_changed").contains(reason)
            &&b.action.equals(v.action)&&b.session.equals(v.session)&&b.player.equals(v.player)&&b.server.equals(v.server)&&b.revision==v.revision
            &&v.nano>=b.sourceNano&&v.nano<b.deadline
            &&(b.sourceWorld.equals(v.world)&&b.sourceDimension.equals(v.dimension)
                ||!b.sourceWorld.equals(v.world)&&b.destination.equals(v.dimension));
    }
    private PortalTransitionPolicy(){}
}
