#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -ne 3 ]]; then echo 'Usage: bash compile.sh PROJECT_ROOT EXISTING_GSON_2_11_0_JAR JDK21_HOME' >&2; exit 2; fi
PROJECT=$(realpath "$1"); GSON=$(realpath "$2"); JDK=$(realpath "$3")
python3 prepare_sources.py "$PROJECT" "$GSON"
mkdir -p .build/classes
find .build/src -name '*.java' -print | sort > .build/sources.list
# An approved serial window is required before invoking this script.
timeout 45s "$JDK/bin/javac" -J-Xms32m -J-Xmx256m -J-XX:ActiveProcessorCount=1 -J-XX:+UseSerialGC --release 21 -cp "$GSON" -d .build/classes @.build/sources.list
