package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** No entity getters: unsupported class rejection precedes spatial classification. */
final class NativeEntityDiagnostics {
    static JsonObject unsupportedClass(Class<?> type,String profile) {
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",profile);
        j.addProperty("enumeration_scope","all_rendered_entities_before_spatial_filter");
        j.addProperty("spatial_filter_applied",false);j.addProperty("spatial_relation","not_evaluated");
        String name=type.getName();j.addProperty("entity_class",name.length()<=256?name:"class_name_exceeds_bound");
        j.addProperty("entity_class_complete",name.length()<=256);
        j.addProperty("reason","scoped_movement_entity_unsupported");j.addProperty("diagnostic_only",true);
        j.addProperty("dispatch_authority",false);return j;
    }
    static ClientActionRequest.Rejected unsupported(Object entity,String profile) {
        return new ClientActionRequest.Rejected(409,"scoped_movement_entity_unsupported")
            .withNativeEntityDiagnostic(unsupportedClass(entity.getClass(),profile));
    }
}
