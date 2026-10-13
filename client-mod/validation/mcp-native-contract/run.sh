#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -ne 4 ]]; then
  echo 'Usage: bash run.sh CLIENT_MOD_ROOT EXISTING_GSON_JAR JDK21_HOME BUILT_CLIENT_JAR' >&2
  exit 2
fi
PROJECT=$(realpath "$1"); GSON=$(realpath "$2"); JDK=$(realpath "$3"); CLIENT_JAR=$(realpath "$4")
SRC="$PROJECT/src/main/java/io/github/campione01/mineclientbridge"
[[ -f "$CLIENT_JAR" && -f "$GSON" && -x "$JDK/bin/java" && -x "$JDK/bin/javac" ]]
mkdir -p .build/classes
# The exact integrated build JAR supplies all production classes. Never compile
# the old pure subset or replace CoordinationStepGuard to bypass its new linkage.
NATIVE_CP="$CLIENT_JAR:$GSON"
sources=(ClientActionRequest ActionRegistry BoatDriveRequest BoatTransferRequest BoatSteering BoundedCombatRequest EncounterRequest CombatThreats CoordinationStepGuard CoordinationStepPolicy)
files=(); for name in "${sources[@]}"; do files+=("$SRC/$name.java"); done
sha256sum "$CLIENT_JAR" "$GSON" "${files[@]}" NativeActionWire.java check-wire.mjs > .build/input-sha256.txt
# Only the emitter is compiled here. The actual parser and registry run from the
# pinned JAR; no Minecraft entrypoint, game, network, loader or substitute is run.
timeout 20s "$JDK/bin/javac" -J-Xms16m -J-Xmx128m -J-XX:ActiveProcessorCount=1 -J-XX:+UseSerialGC --release 21 -cp "$NATIVE_CP" -d .build/classes NativeActionWire.java
timeout 10s "$JDK/bin/java" -Xms16m -Xmx128m -XX:ActiveProcessorCount=1 -XX:+UseSerialGC -cp "$NATIVE_CP:.build/classes" io.github.campione01.mineclientbridge.NativeActionWire > .build/native-wire.json
node check-wire.mjs .build/native-wire.json
