#!/usr/bin/env bash
# Offline only. Never launches Minecraft, touches a runtime journal, or writes the frozen input candidate.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$(cd "$HERE/../../.." && pwd)"
CANDIDATE="$(dirname "$SOURCE")"
WORKSPACE="$(dirname "$CANDIDATE")"
OUT="${1:-$CANDIDATE/results/native/reproduce}"
mkdir -p "$OUT/classes-production" "$OUT/classes-tests" "$OUT/logs"
# A new output directory avoids stale class files. Do not use this on a packaged/live class directory.
if find "$OUT/classes-production" "$OUT/classes-tests" -type f -name '*.class' -print -quit | grep -q .; then
  echo 'Refusing nonempty class output; choose a fresh offline output directory.' >&2; exit 2
fi
CP="$(cat "$WORKSPACE/minecraft-runtime/compile-classpath-at.txt")"
JAVAC="$WORKSPACE/minecraft-runtime/local-jdk-tools/javac"
find "$SOURCE/client-mod/src/main/java" -name '*.java' | sort > "$OUT/java-sources.txt"
"$JAVAC" -proc:none -source 21 -target 21 -cp "$CP" -d "$OUT/classes-production" @"$OUT/java-sources.txt" > "$OUT/logs/compile-production.log" 2>&1
"$JAVAC" -proc:none -source 21 -target 21 -cp "$OUT/classes-production:$CP" -d "$OUT/classes-tests" \
  "$SOURCE/client-mod/validation/recovery-short-input/"*.java "$HERE/"*.java > "$OUT/logs/compile-tests.log" 2>&1
RUNCP="$OUT/classes-tests:$OUT/classes-production:$CP"
java -DmineclientBridge.recoveryInteractionV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryShortInputChecks > "$OUT/logs/legacy-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryShortInputWireChecks "$OUT/legacy-wire-check" > "$OUT/logs/legacy-codec.log" 2>&1
java -DmineclientBridge.recoveryInteractionV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks "$CANDIDATE/results/legacy57-fixtures" "$OUT" --preserve-fixtures > "$OUT/logs/interaction-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionPinnedChecks \
  "$WORKSPACE/minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar" > "$OUT/logs/pinned-selectors.log" 2>&1
java -DmineclientBridge.recoveryInteractionV1=true -DmineclientBridge.recoveryShortInputV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks --both-flags > "$OUT/logs/both-flags.log" 2>&1
cat "$OUT/logs/"*.log
