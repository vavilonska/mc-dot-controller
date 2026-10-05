#!/usr/bin/env python3
"""Static safety-contract checks; does not replace compilation or a live integration test."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
java = root / 'src/main/java/io/github/campione01/mineclientbridge'
reader = (java / 'TerrainReader.java').read_text()
server = (java / 'BridgeServer.java').read_text()
query = (java / 'TerrainQuery.java').read_text()
scan = (java / 'TerrainScan.java').read_text()
assert 'getChunk(x >> 4, z >> 4, ChunkStatus.FULL, false)' in reader
assert 'if (!mc.isSameThread())' in reader
assert 'implements BlockGetter' in reader and '++reads > 64' in reader
assert 'collision_unknown_reason' in reader and 'hazards_exhaustive", false' in reader
for forbidden in ['setBlock(', 'sendCommand(', 'getConnection(', 'getChunkAt(', 'setBlockState(']:
    assert forbidden not in reader, forbidden
assert 'requireControlAccess(exchange, "/control/terrain", "GET")' in server
assert 'TERRAIN_DISPATCH.call(' in server
assert '() -> {' in server[server.index('private static void handleControlTerrain'):server.index('private static void handleControlScreen')]
assert 'Minecraft.getInstance().execute' in server[server.index('private static void handleControlTerrain'):server.index('private static void handleControlScreen')]
for bound in ['MAX_RADIUS = 16', 'MAX_VERTICAL = 8', 'MAX_LIMIT = 128', 'MAX_BLOCKS = 18_513']:
    assert bound in query, bound
assert 'Availability.LOADED ? source.readLoaded' in scan
assert 'PAGE_BUDGET_NANOS = 2_000_000L' in scan
assert 'MIN_PAGE_INTERVAL_NANOS = 50_000_000L' in scan
assert 'currentWorld' in scan and 'stale_terrain_cursor' in scan
print('Terrain static safety-contract audit passed')
