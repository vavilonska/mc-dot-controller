package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
public final class CompactTerrainDiagnosticWire {
    public static void main(String[]args)throws Exception{
        long[] now={0};var scan=CompactTerrainScan.read(1,0,65,0,()->now[0],(x,y,z)->{now[0]+=2_000_000;return new CompactTerrainScan.Cell(x,y,z,"loaded","minecraft:stone");});
        var diagnostic=new CompactObservation.Diagnostic(new CompactObservation.Request("compact-cost-one",1),0);
        diagnostic.enter("terrain_ids",0);diagnostic.terrain(scan);
        JsonObject body=new ClientActionRequest.Rejected(409,"compact_observation_terrain_budget_exhausted").response();
        body.add("compact_observation_diagnostic",diagnostic.json(9_000_000));System.out.println(BridgeJson.toJson(body));
    }
}
