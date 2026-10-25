package io.github.campione01.mineclientbridge;

import com.mojang.logging.LogUtils;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.DeathScreen;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.contents.TranslatableContents;
import org.lwjgl.glfw.GLFW;
import org.lwjgl.glfw.GLFWMouseButtonCallbackI;
import org.slf4j.Logger;

/** Opt-in human left-click for exactly the existing vanilla Respawn button; no generic input route. */
public final class RecoveryDeathScreenUi {
    private static final boolean FLAG=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryDeathScreenUi","false"));
    private static final Logger LOGGER=LogUtils.getLogger();
    private static final RecoveryRespawnUiGate GATE=new RecoveryRespawnUiGate();
    private static final GLFWMouseButtonCallbackI BUTTON=RecoveryDeathScreenUi::hardwareButton;
    private static long registeredWindow;
    private static Binding pending;
    private static final java.util.Set<String> REPORTED_REFUSALS=java.util.concurrent.ConcurrentHashMap.newKeySet();
    private record Binding(LocalPlayer player,Object level,Object gameMode,Object server,Object connection,DeathScreen screen,Button button,Button title) { }
    static boolean enabled(){if(RecoverySurvivalV6.ENABLED)return FLAG&&!RecoveryMaintenanceV5.ENABLED&&!RecoveryNavigationV4.ENABLED&&!RecoveryInteraction.V3_ENABLED&&!RecoveryInteraction.V2_ENABLED&&!RecoveryInteraction.ENABLED&&!NativeRecoveryShortInput.LEGACY_ENABLED&&ClientInputIsolation.enabled();if(RecoveryMaintenanceV5.ENABLED)return FLAG&&!RecoveryNavigationV4.ENABLED&&!RecoveryInteraction.V3_ENABLED&&!RecoveryInteraction.V2_ENABLED&&!RecoveryInteraction.ENABLED&&!NativeRecoveryShortInput.LEGACY_ENABLED&&ClientInputIsolation.enabled();return flagsV4(FLAG,RecoveryNavigationV4.ENABLED,RecoveryInteraction.V3_ENABLED,RecoveryInteraction.V2_ENABLED,RecoveryInteraction.ENABLED,NativeRecoveryShortInput.LEGACY_ENABLED,ClientInputIsolation.enabled());}
    static boolean flagsV4(boolean flag,boolean v4,boolean v3,boolean v2,boolean v1,boolean legacy,boolean isolated){return flag&&(v4^v3)&&!v2&&!v1&&!legacy&&isolated;}
    static boolean flags(boolean flag,boolean v3,boolean v2,boolean v1,boolean legacy,boolean isolated){return flag&&v3&&!v2&&!v1&&!legacy&&isolated;}
    static boolean exactActorClasses(Class<?> player,Class<?> screen){return player==LocalPlayer.class&&screen==DeathScreen.class;}
    static boolean exactButtonClass(Class<?> button){return button==Button.class;}
    public static void install(long window){
        if(!enabled()||window==0)return;
        registeredWindow=window;GLFW.glfwSetMouseButtonCallback(window,BUTTON);
    }
    static boolean blocksStarts(){return enabled()&&GATE.blocksStarts();}
    static boolean claimIdle(RecoveryShortInputLedger ledger,Object player,boolean captureAbsent){return enabled()&&GATE.claimIdle(ledger,player,captureAbsent);}
    private static void refused(String reason){if(REPORTED_REFUSALS.add(reason)){LOGGER.info("MDC_RESPAWN_UI refusal={}",reason);}}
    private static void hardwareButton(long window,int button,int action,int modifiers){
        // Releases and all non-left presses never reach MouseHandler or KeyMapping.
        if(!acceptPress(enabled(),button,action,modifiers))return;
        Minecraft mc=Minecraft.getInstance();
        if(!mc.isSameThread()){refused("wrong_thread");return;}
        if(window==0||window!=registeredWindow||window!=mc.getWindow().getWindow()){refused("wrong_window");return;}
        if(GATE.consumed()){refused("already_consumed");return;}
        Binding binding;double guiX=0,guiY=0;
        try{
            binding=binding(mc);if(binding==null){refused("ineligible_context_or_button");return;}
            double[] x={0},y={0};GLFW.glfwGetCursorPos(window,x,y);
            int width=mc.getWindow().getScreenWidth(),height=mc.getWindow().getScreenHeight();
            if(width<=0||height<=0){refused("invalid_window_geometry");return;}
            guiX=x[0]*mc.getWindow().getGuiScaledWidth()/width;guiY=y[0]*mc.getWindow().getGuiScaledHeight()/height;
            if(!hit(binding.button(),guiX,guiY)){refused("outside_respawn_button");return;}
            // No sound, screen event, scheduling or logger callback between this final native check and original onPress.
            if(!sameBinding(mc,binding)||!NativeRecoveryShortInput.claimDeathScreenUi(binding.player())){refused("native_not_idle_or_changed");return;}
            pending=binding;
        }catch(RuntimeException failure){refused("preclaim_reader_failed");return;}
        // The claim has consumed the one attempt and blocked HTTP starts under the same journal monitor.
        try{
            LOGGER.info("MDC_RESPAWN_UI stage=claimed consumed=true native_starts_blocked=true");
            if(window!=registeredWindow||window!=mc.getWindow().getWindow()||!sameBinding(mc,binding)||!hit(binding.button(),guiX,guiY)){GATE.failed(binding.player());LOGGER.warn("MDC_RESPAWN_UI stage=final_context_unknown consumed=true native_starts_blocked=true");return;}
            binding.button().onPress();GATE.returned(binding.player());LOGGER.info("MDC_RESPAWN_UI stage=returned awaiting_native_replacement=true");}
        catch(RuntimeException|Error failure){GATE.failed(binding.player());LOGGER.warn("MDC_RESPAWN_UI stage=unknown consumed=true native_starts_blocked=true");}
    }
    private static Binding binding(Minecraft mc){
        if(mc.player==null||mc.screen==null||!exactActorClasses(mc.player.getClass(),mc.screen.getClass())||mc.level==null||mc.gameMode==null
            ||mc.getOverlay()!=null
            ||!mc.player.isDeadOrDying()||!CapabilityGuard.privateSingleplayer(mc)||mc.level.getLevelData().isHardcore())return null;
        var screen=(DeathScreen)mc.screen;var children=screen.children();
        if(children.size()!=2||!exactButtonClass(children.get(0).getClass())||!exactButtonClass(children.get(1).getClass()))return null;
        var button=(Button)children.get(0);var title=(Button)children.get(1);
        if(!translation(button,"deathScreen.respawn")||!translation(title,"deathScreen.titleScreen")
            ||!button.active||!button.visible||button.getX()!=screen.width/2-100||button.getY()!=screen.height/4+72
            ||button.getWidth()!=200||button.getHeight()!=20)return null;
        return new Binding(mc.player,mc.level,mc.gameMode,mc.getSingleplayerServer(),mc.getConnection(),screen,button,title);
    }
    private static boolean translation(Button button,String key){return button.getMessage().getContents() instanceof TranslatableContents value&&key.equals(value.getKey());}
    static boolean acceptPress(boolean enabled,int button,int action,int modifiers){return enabled&&button==GLFW.GLFW_MOUSE_BUTTON_LEFT&&action==GLFW.GLFW_PRESS&&modifiers==0;}
    static boolean hitBounds(double x,double y,int left,int top,int width,int height){return Double.isFinite(x)&&Double.isFinite(y)&&width>0&&height>0&&x>=left&&x<(double)left+width&&y>=top&&y<(double)top+height;}
    private static boolean hit(Button button,double x,double y){return hitBounds(x,y,button.getX(),button.getY(),button.getWidth(),button.getHeight());}
    private static boolean sameBinding(Minecraft mc,Binding b){
        return mc.player==b.player()&&mc.level==b.level()&&mc.gameMode==b.gameMode()&&mc.getSingleplayerServer()==b.server()
            &&mc.getConnection()==b.connection()&&mc.screen==b.screen()&&mc.getOverlay()==null&&b.player().isDeadOrDying()
            &&CapabilityGuard.privateSingleplayer(mc)&&!mc.level.getLevelData().isHardcore()
            &&b.screen().children().size()==2&&b.screen().children().get(0)==b.button()&&b.screen().children().get(1)==b.title()
            &&translation(b.button(),"deathScreen.respawn")&&translation(b.title(),"deathScreen.titleScreen")
            &&b.button().active&&b.button().visible&&b.button().getX()==b.screen().width/2-100&&b.button().getY()==b.screen().height/4+72
            &&b.button().getWidth()==200&&b.button().getHeight()==20;
    }
    static void observeLifecycle(Minecraft mc){
        if(!enabled()||pending==null||GATE.phase()!=RecoveryRespawnUiGate.Phase.AWAITING_RESPAWN)return;
        var b=pending;
        try{
            boolean context=mc.isSameThread()&&mc.getSingleplayerServer()==b.server()&&mc.getConnection()==b.connection()&&mc.gameMode==b.gameMode();
            boolean alive=mc.player!=null&&mc.player.getClass()==LocalPlayer.class&&mc.level!=null&&mc.player.isAlive()&&!mc.player.isDeadOrDying()
                &&mc.screen!=b.screen()&&!(mc.screen instanceof DeathScreen);
            if(GATE.replacement(b.player(),mc.player,context,alive))LOGGER.info("MDC_RESPAWN_UI stage=native_replacement_observed starts_unblocked=true consumed=true");
            else if(GATE.phase()==RecoveryRespawnUiGate.Phase.UNKNOWN)LOGGER.warn("MDC_RESPAWN_UI stage=context_unknown native_starts_blocked=true consumed=true");
        }catch(RuntimeException|Error failure){GATE.failed(b.player());LOGGER.warn("MDC_RESPAWN_UI stage=observation_unknown native_starts_blocked=true consumed=true");}
    }
    private RecoveryDeathScreenUi(){}
}
