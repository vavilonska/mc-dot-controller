#!/usr/bin/env bash
# Offline compile and journal/codec/pinned-resource checks only; no game/runtime mutation.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$(cd "$HERE/../../.." && pwd)"
CANDIDATE="$(dirname "$SOURCE")"
WORKSPACE="$(dirname "$CANDIDATE")"
OUT="${1:-$CANDIDATE/results/native/reproduce}"
mkdir -p "$OUT/classes-production" "$OUT/classes-tests" "$OUT/logs"
if find "$OUT/classes-production" "$OUT/classes-tests" -name '*.class' -print -quit | grep -q .; then echo 'Choose fresh offline class output.' >&2; exit 2; fi
CP="$(cat "$WORKSPACE/minecraft-runtime/compile-classpath-at.txt")"
JAVAC="$WORKSPACE/minecraft-runtime/local-jdk-tools/javac"
find "$SOURCE/client-mod/src/main/java" -name '*.java' | sort > "$OUT/java-sources.txt"
"$JAVAC" -proc:none -source 21 -target 21 -cp "$CP" -d "$OUT/classes-production" @"$OUT/java-sources.txt" > "$OUT/logs/compile-production.log" 2>&1
"$JAVAC" -proc:none -source 21 -target 21 -cp "$OUT/classes-production:$CP" -d "$OUT/classes-tests" "$SOURCE/client-mod/validation/recovery-short-input/"*.java "$SOURCE/client-mod/validation/recovery-interaction/"*.java "$HERE/"*.java > "$OUT/logs/compile-tests.log" 2>&1
RUNCP="$OUT/classes-tests:$OUT/classes-production:$CP"
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryShortInputChecks > "$OUT/logs/legacy-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryShortInputWireChecks "$OUT/legacy-wire-check" > "$OUT/logs/legacy-codec.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks "$WORKSPACE/mdc-recovery-interaction-test-r1/results/legacy57-fixtures" "$OUT/v1-regression" --preserve-fixtures > "$OUT/logs/v1-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionPinnedChecks "$WORKSPACE/minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar" > "$OUT/logs/pinned-selectors.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionV2Checks "$CANDIDATE/results/legacy94-fixtures" "$OUT" > "$OUT/logs/v2-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryWartPinnedChecks "$WORKSPACE/minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar" "$WORKSPACE/minecraft-runtime/versions/1.21.1/1.21.1.jar" "$OUT/wart-pinned-audit.json" > "$OUT/logs/wart-pinned.log" 2>&1
for old in recoveryShortInputV1 recoveryInteractionV1; do
 java -DmineclientBridge.recoveryInteractionV2=true -DmineclientBridge.$old=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks --both-flags > "$OUT/logs/flags-v2-$old.log" 2>&1
done
java -DmineclientBridge.recoveryShortInputV1=true -DmineclientBridge.recoveryInteractionV1=true -cp "$RUNCP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks --both-flags > "$OUT/logs/flags-legacy-pair.log" 2>&1
cat "$OUT/logs/"*.log
