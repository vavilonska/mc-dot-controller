#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${JAVA_HOME:?Set JAVA_HOME to a Java 21 JDK}"
out="build/guarded-action-core-tests"
mkdir -p "$out"
"$JAVA_HOME/bin/javac" -encoding UTF-8 --release 21 -d "$out" \
  src/main/java/io/github/campione01/mineclientbridge/GuardedAction.java \
  src/main/java/io/github/campione01/mineclientbridge/GuardedDispatch.java \
  src/test/java/io/github/campione01/mineclientbridge/GuardedActionChecks.java
"$JAVA_HOME/bin/java" -cp "$out" io.github.campione01.mineclientbridge.GuardedActionChecks
