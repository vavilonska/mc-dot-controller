package io.github.campione01.mineclientbridge;
import java.lang.reflect.Field;
import java.util.List;
/** Actual plain-field settings writes. No callbacks, retries, or overwrite of a changed value. */
final class ManagedSettingsValues {
    record Value(Object setting,Object original,Object installed){}
    private final Field field;private final List<Value> values;private boolean attempted,restored;
    ManagedSettingsValues(Field field,List<Value> values){this.field=field;this.values=List.copyOf(values);}
    void install()throws IllegalAccessException{
        if(attempted)throw new IllegalStateException("managed_navigation_settings_not_repeatable");
        for(Value v:values)if(field.get(v.setting())!=v.original())throw new IllegalStateException("managed_navigation_settings_changed_before_install");
        attempted=true;
        for(Value v:values)field.set(v.setting(),v.installed());
    }
    boolean unchanged()throws IllegalAccessException{
        if(!attempted||restored)return false;
        for(Value v:values)if(field.get(v.setting())!=v.installed())return false;
        return true;
    }
    void restore()throws IllegalAccessException{
        if(!unchanged())throw new IllegalStateException("managed_navigation_settings_changed_do_not_overwrite");
        for(Value v:values)field.set(v.setting(),v.original());
        restored=true;
    }
}
