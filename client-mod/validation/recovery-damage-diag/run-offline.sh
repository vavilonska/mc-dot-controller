#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; SOURCE="$(cd "$HERE/../../.." && pwd)"; CANDIDATE="$(dirname "$SOURCE")"; WORKSPACE="$(dirname "$CANDIDATE")"; OUT="$1"
mkdir -p "$OUT/classes-production" "$OUT/classes-tests" "$OUT/logs"
if find "$OUT/classes-production" -name '*.class' -print -quit | grep -q .; then echo 'Choose fresh output' >&2; exit 2; fi
CP="$(cat "$WORKSPACE/minecraft-runtime/compile-classpath-at.txt")"; JAVAC="$WORKSPACE/minecraft-runtime/local-jdk-tools/javac"
find "$SOURCE/client-mod/src/main/java" -name '*.java' | sort > "$OUT/java-sources.txt"
"$JAVAC" -proc:none -source 21 -target 21 -cp "$CP" -d "$OUT/classes-production" @"$OUT/java-sources.txt" > "$OUT/logs/compile-production.log" 2>&1
"$JAVAC" -proc:none -source 21 -target 21 -cp "$OUT/classes-production:$CP" -d "$OUT/classes-tests" "$SOURCE/client-mod/validation/recovery-short-input/"*.java "$SOURCE/client-mod/validation/recovery-interaction/"*.java "$SOURCE/client-mod/validation/recovery-interaction-v2/"*.java "$HERE/"*.java > "$OUT/logs/compile-tests.log" 2>&1
CP="$OUT/classes-tests:$OUT/classes-production:$CP"
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryDamageDiagnosticChecks "$OUT/wire-fixtures" "$WORKSPACE/minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar" > "$OUT/logs/diagnostic-checks.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryShortInputChecks > "$OUT/logs/legacy-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryShortInputWireChecks "$OUT/legacy-wire" > "$OUT/logs/legacy-wire.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryInteractionChecks "$WORKSPACE/mdc-recovery-interaction-test-r1/results/legacy57-fixtures" "$OUT/v1-regression" --preserve-fixtures > "$OUT/logs/v1-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryInteractionV2Checks "$WORKSPACE/mdc-recovery-interaction-test-r2/results/legacy94-fixtures" "$OUT/v2-regression" > "$OUT/logs/v2-core.log" 2>&1
java -DmineclientBridge.recoveryInteractionV2=true -cp "$CP" io.github.campione01.mineclientbridge.RecoveryInteractionPinnedChecks "$WORKSPACE/minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar" > "$OUT/logs/pinned-checks.log" 2>&1
cat "$OUT/logs/"*.log
