#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -ne 3 ]]; then echo 'Usage: bash run.sh CLIENT_MOD_ROOT EXISTING_GSON_JAR JDK21_HOME' >&2; exit 2; fi
PROJECT=$(realpath "$1"); GSON=$(realpath "$2"); JDK=$(realpath "$3")
python3 prepare_sources.py "$PROJECT"
mkdir -p .build/classes
find .build/src -name '*.java' -print | sort > .build/sources.list
# Requires an approved serial JVM window. No download, network, or game entrypoint.
timeout 30s "$JDK/bin/javac" -J-Xms16m -J-Xmx128m -J-XX:ActiveProcessorCount=1 -J-XX:+UseSerialGC --release 21 -cp "$GSON" -d .build/classes @.build/sources.list
timeout 10s "$JDK/bin/java" -Xms16m -Xmx128m -XX:ActiveProcessorCount=1 -XX:+UseSerialGC -cp ".build/classes:$GSON" io.github.campione01.mineclientbridge.ContainerAdapterChecks
