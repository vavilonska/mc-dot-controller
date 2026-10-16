package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Locale;
import java.util.Set;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;

/** Bounded diagnostic facts only. Never authorizes a retry, defense or known settlement. */
final class RouteEntityDiagnostics {
    enum Phase { ENUMERATION, IDENTITY, TYPE, GEOMETRY, STATE, POLICY, COVERAGE, FRESHNESS, COMPARE }
    private final boolean bees;
    RouteEntityDiagnostics(){this(false);}
    RouteEntityDiagnostics(boolean bees){this.bees=bees;}
    private Phase phase=Phase.ENUMERATION;
    private String type="type_unavailable";
    private ScopedRouteStopPolicy.Row beeRow;
    private NativeLivingObservation.Frame beeFrame;
    private RouteBeeDiagnostics.Context beeContext;
    void context(RouteBeeDiagnostics.Context context){beeContext=context;}
    RouteBeeDiagnostics.Context context(){return beeContext;}
    void bee(ScopedRouteStopPolicy.Row row,NativeLivingObservation.Frame frame){if(bees){beeRow=row;beeFrame=frame;}}
    private static final Set<String> CODES=Set.of("route_bee_native_unconfirmed","route_bee_native_stale","route_bee_not_calm","route_bee_native_context_changed","route_stop_coverage_invalid","route_stop_duplicate_identity","route_stop_entity_state_unknown","route_stop_entity_unsupported","route_stop_evidence_too_large","route_stop_far_context_conflict","route_stop_geometry_missing","route_stop_identity_invalid","route_stop_order_invalid","route_stop_projected_body_conflict","route_stop_projection_changed","route_stop_removed_shape","scoped_movement_entities_changed_after_hooks","scoped_movement_entity_box_invalid","scoped_movement_entity_capture_stale","scoped_movement_entity_coverage_invalid","scoped_movement_entity_coverage_limit","scoped_movement_entity_duplicate_identity","scoped_movement_entity_duplicate_object","scoped_movement_entity_evidence_too_large","scoped_movement_entity_fire_reader_unavailable","scoped_movement_entity_geometry_missing","scoped_movement_entity_health_nonfinite","scoped_movement_entity_horizon_invalid","scoped_movement_entity_identity_missing","scoped_movement_entity_nonfinite","scoped_movement_entity_order_invalid","scoped_movement_entity_projected_corridor_conflict","scoped_movement_entity_projection_changed","scoped_movement_entity_projection_nonfinite","scoped_movement_entity_self_coverage","scoped_movement_entity_state_unknown","scoped_movement_entity_target_present","scoped_movement_entity_tick_budget","scoped_movement_entity_unsupported","scoped_movement_entity_uuid_invalid","scoped_movement_removed_entity_reader_unknown","scoped_movement_removed_entity_shape","scoped_movement_response_evidence_too_large");
    void phase(Phase phase){this.phase=phase;}
    void typeUnavailable(){type="type_unavailable";beeRow=null;beeFrame=null;}
    void trustedType(String value){type=value!=null&&value.length()<=128&&value.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")?value:"type_unavailable";}
    void entityType(Entity entity){
        try {
            // Do not call an unknown override for even a diagnostic fact.
            if(entity.getClass().getMethod("getType").getDeclaringClass()!=Entity.class)return;
            var key=BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType());
            if(key!=null)trustedType(key.toString());
        }catch(ReflectiveOperationException|RuntimeException ignored){typeUnavailable();}
    }
    ClientActionRequest.Rejected rejection(RuntimeException failure){
        String raw=failure.getMessage();String code=raw!=null&&CODES.contains(raw)?raw:"scoped_movement_entity_coverage_unknown";
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",bees?ScopedRouteStopPolicy.PROFILE_V2:ScopedRouteStopPolicy.PROFILE);
        j.addProperty("policy",bees?ScopedRouteStopPolicy.POLICY_V2:ScopedRouteStopPolicy.POLICY);j.addProperty("phase",phase.name().toLowerCase(Locale.ROOT));
        j.addProperty("entity_type",type);j.addProperty("exception_type",failure instanceof ClientActionRequest.Rejected||failure instanceof IllegalArgumentException?"rejected":"runtime_exception");j.addProperty("rejection_code",code);
        if(bees&&ScopedRouteStopPolicy.BEE.equals(type)&&beeRow!=null){
            JsonObject detail=RouteBeeDiagnostics.json(beeRow,beeFrame,beeContext);
            if(detail!=null){j.addProperty("schema_version",2);j.add("native_bee_diagnostic",detail);}
        }
        return new ClientActionRequest.Rejected(409,code,null,null,j);
    }
}
