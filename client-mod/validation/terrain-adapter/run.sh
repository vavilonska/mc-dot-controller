#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -ne 2 ]]; then echo 'Usage: bash run.sh EXISTING_GSON_2_11_0_JAR JDK21_HOME' >&2; exit 2; fi
GSON=$(realpath "$1"); JDK=$(realpath "$2")
# An approved serial window is required; never overlap live game evidence capture.
for name in FiniteAdapterChecks io.github.campione01.mineclientbridge.TerrainCoreChecks io.github.campione01.mineclientbridge.TerrainDispatchChecks io.github.campione01.mineclientbridge.FlatStepCorridorChecks; do
  timeout 45s "$JDK/bin/java" -Xms32m -Xmx192m -XX:ActiveProcessorCount=1 -XX:+UseSerialGC -cp ".build/classes:$GSON" "$name" .build/results.json
done
