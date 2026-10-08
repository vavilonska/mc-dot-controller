#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${JAVA_HOME:?Set JAVA_HOME to a Java 21 JDK}"
out="build/terrain-core-tests"
mkdir -p "$out"
"$JAVA_HOME/bin/javac" -encoding UTF-8 --release 21 -d "$out" \
  src/main/java/io/github/campione01/mineclientbridge/TerrainQuery.java \
  src/main/java/io/github/campione01/mineclientbridge/TerrainScan.java \
  src/main/java/io/github/campione01/mineclientbridge/TerrainDispatch.java \
  src/main/java/io/github/campione01/mineclientbridge/WorldGeneration.java \
  src/test/java/io/github/campione01/mineclientbridge/TerrainCoreChecks.java \
  src/test/java/io/github/campione01/mineclientbridge/TerrainDispatchChecks.java
"$JAVA_HOME/bin/java" -cp "$out" io.github.campione01.mineclientbridge.TerrainCoreChecks

"$JAVA_HOME/bin/java" -cp "$out" io.github.campione01.mineclientbridge.TerrainDispatchChecks
