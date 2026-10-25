#!/usr/bin/env bash
set -euo pipefail
# Compile/test only. Requires a separately compiled, exact integration source tree.
root=$(cd "$(dirname "$0")/../../.." && pwd)
: "${JAVA_HOME:?Set the pinned official JDK21}"
: "${MDC_COMPILE_CLASSPATH:?Set the official compile-classpath-at.txt path}"
classes=${1:?Pass the previously compiled integration classes directory}
out=${2:?Pass a new output directory outside the source tree}
cp=$(cat "$MDC_COMPILE_CLASSPATH")
export PYTHONDONTWRITEBYTECODE=1
export JAVA_TOOL_OPTIONS='-Xmx256m'
"$root/client-mod/validation/typed-portals/run-policies.sh" "$out/policies"
mkdir -p "$out/native-test-classes"
"$JAVA_HOME/bin/javac" -J-Xmx256m -proc:none --release 21 -cp "$classes:$cp" -d "$out/native-test-classes" \
  "$root/client-mod/validation/typed-portals/TypedPortalIntentChecks.java" \
  "$root/client-mod/validation/typed-portals/TypedItemArgumentNativeChecks.java"
"$JAVA_HOME/bin/java" -Xmx256m -cp "$out/native-test-classes:$classes:$cp" io.github.campione01.mineclientbridge.TypedPortalIntentChecks "$out/policies/intent-cases.json"
"$JAVA_HOME/bin/java" -Xmx256m -cp "$out/native-test-classes:$classes:$cp" io.github.campione01.mineclientbridge.TypedItemArgumentNativeChecks
