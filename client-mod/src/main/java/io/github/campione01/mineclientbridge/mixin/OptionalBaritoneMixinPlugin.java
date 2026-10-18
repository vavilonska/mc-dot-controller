package io.github.campione01.mineclientbridge.mixin;

import java.io.InputStream;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.objectweb.asm.tree.ClassNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

/** Unsupported or absent optional mods receive no transformation and no walking authority. */
public final class OptionalBaritoneMixinPlugin implements IMixinConfigPlugin {
    static boolean supported(ClassLoader loader) {
        try {
            for(var pin:Map.of("baritone/fj.class","98e6529f3c0d15278aedd9818c6ec9c811c118bfe33c1618ade6620e1c013a7f",
                "baritone/api/BaritoneAPI.class","e0e4d6d2348b9fe892127944b98c2abbf3da854277f4f7577ce60a24a61660c9").entrySet())
                try(InputStream in=loader.getResourceAsStream(pin.getKey())) {
                    if(in==null)return false;byte[] bytes=in.readNBytes(1_048_577);
                    if(bytes.length>1_048_576||!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(pin.getValue()))return false;
                }
            return true;
        }catch(Exception|LinkageError unavailable){return false;}
    }
    public void onLoad(String mixinPackage){}
    public String getRefMapperConfig(){return null;}
    public boolean shouldApplyMixin(String targetClassName,String mixinClassName){
        return targetClassName.equals("baritone.fj")&&mixinClassName.endsWith(".ManagedNavigationInputMixin")
            &&supported(getClass().getClassLoader());}
    public void acceptTargets(Set<String> myTargets,Set<String> otherTargets){}
    public List<String> getMixins(){return null;}
    public void preApply(String targetClassName,ClassNode targetClass,String mixinClassName,IMixinInfo mixinInfo){}
    public void postApply(String targetClassName,ClassNode targetClass,String mixinClassName,IMixinInfo mixinInfo){}
}
