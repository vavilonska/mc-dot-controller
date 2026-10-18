package io.github.campione01.mineclientbridge;

import java.io.InputStream;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

/** Temporary same-lease walking configuration; never overwrites a changed value on restore. */
final class ManagedNavigationSettings {
    private static final Map<String,String> PINS=Map.of(
        "baritone/api/Settings.class","e435ed5c1fafe8f323b93a40841bf2acea975b509b2c1f94f5d7996b762308ed",
        "baritone/api/Settings$Setting.class","8e115e47fd1cfe52cc9f25e778f1274d16611734e2bfc1685400793f872b0562",
        "baritone/api/pathing/goals/GoalBlock.class","0d5c794e33de058ec2a8b9d8c6385077dd21b1457f5df51c876927b776826e8c",
        "baritone/api/process/ICustomGoalProcess.class","4aa409f9c952686db189e97045dc10b7c4f852d68f263cc212e959207b1a2d0d",
        "baritone/api/process/PathingCommand.class","ffb89874152a985b26a2bb08699ff8fd93148eb84c942c4b974349406ddcdb21");
    private final List<ManagedSettingsValues.Value> values=new ArrayList<>();
    private final Object settings;
    private final Field valueField;
    private final ManagedSettingsValues journal;
    private static Boolean verified;
    static void verify(ClassLoader loader) throws Exception {
        if(Boolean.TRUE.equals(verified))return;
        for(var entry:PINS.entrySet())try(InputStream in=loader.getResourceAsStream(entry.getKey())) {
            if(in==null)throw new IllegalStateException("managed_navigation_api_bytes_missing");
            byte[] bytes=in.readNBytes(1_048_577);
            if(bytes.length>1_048_576||!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(entry.getValue()))
                throw new IllegalStateException("managed_navigation_api_binary_unsupported");
        }
        verified=true;
    }
    ManagedNavigationSettings(ClassLoader loader) throws Exception {
        verify(loader);
        Class<?> api=Class.forName("baritone.api.BaritoneAPI",false,loader),type=Class.forName("baritone.api.Settings",false,loader);
        settings=api.getMethod("getSettings").invoke(null);
        if(settings==null||settings.getClass()!=type)throw new IllegalStateException("managed_navigation_settings_changed");
        Class<?> settingType=Class.forName("baritone.api.Settings$Setting",false,loader);
        valueField=settingType.getField("value");
        for(String name:List.of("allowBreak","allowPlace","allowSprint","allowInventory","autoTool","assumeExternalAutoTool",
                "allowWaterBucketFall","allowParkour","allowParkourPlace","allowParkourAscend","allowDiagonalDescend",
                "allowDiagonalAscend","allowDownward","allowVines","assumeWalkOnWater","assumeWalkOnLava","assumeStep",
                "assumeSafeWalk","disconnectOnArrival","rightClickContainerOnArrival","enterPortal","backfill","sprintInWater",
                "sprintAscends","allowOvershootDiagonalDescend","notificationOnPathComplete","simplifyUnloadedYCoord","pathThroughCachedOnly"))
            add(type,settingType,name,Boolean.FALSE,Boolean.class);
        add(type,settingType,"cutoffAtLoadBoundary",Boolean.TRUE,Boolean.class);
        add(type,settingType,"maxFallHeightNoWater",Integer.valueOf(1),Integer.class);
        add(type,settingType,"allowBreakAnyway",List.of(),List.class);
        journal=new ManagedSettingsValues(valueField,values);
    }
    private void add(Class<?> type,Class<?> settingType,String name,Object installed,Class<?> valueType) throws Exception {
        Object setting=type.getField(name).get(settings);
        if(setting==null||setting.getClass()!=settingType)throw new IllegalStateException("managed_navigation_setting_class_changed");
        Object original=valueField.get(setting);
        if(!valueType.isInstance(original))throw new IllegalStateException("managed_navigation_setting_type_changed");
        values.add(new ManagedSettingsValues.Value(setting,original,installed));
    }
    void install() throws Exception {journal.install();}
    boolean unchanged() throws Exception {return journal.unchanged();}
    void restore() throws Exception {journal.restore();}
}
