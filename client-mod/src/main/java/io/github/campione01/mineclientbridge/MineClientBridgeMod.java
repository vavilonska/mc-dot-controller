package io.github.campione01.mineclientbridge;

import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import org.apache.logging.log4j.Logger;

@Mod(value = MineClientBridgeMod.MOD_ID, dist = Dist.CLIENT)
public final class MineClientBridgeMod {
    public static final String MOD_ID = "mineclient_bridge";
    public static final Logger LOGGER = BridgeLog.LOGGER;

    public MineClientBridgeMod(IEventBus modEventBus) {
        InputEventProbe.install();
        GuardedGameMovement.install();
        ClientActions.install();
        LoadedWorldScanner.install();
        NativeLivingObservation.install();
        ObservationClockBridge.install();
        net.neoforged.neoforge.common.NeoForge.EVENT_BUS.addListener(
                net.neoforged.neoforge.client.event.ClientTickEvent.Post.class,
                event -> BridgeServer.terrainAcquisitionTick());
        RecoveryDamageDiagnostics.install();
        BridgeServer.start();
        Runtime.getRuntime().addShutdownHook(new Thread(
                BridgeServer::stop,
                "MineClient-Bridge-Shutdown"));
    }
}
