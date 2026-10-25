#!/usr/bin/env bash
set -euo pipefail
# Source-only tests. No Minecraft launch, native-input dispatch, deployment, or server.
root=$(cd "$(dirname "$0")/../../.." && pwd)
: "${JAVA_HOME:?Set JAVA_HOME to the pinned official JDK21}"
out=${1:?Pass an empty/new result directory}
mkdir -p "$out/classes"
j="$root/client-mod/src/main/java/io/github/campione01/mineclientbridge"
"$JAVA_HOME/bin/javac" --release 21 -d "$out/classes" \
  "$j/ItemInteractionSettlementPolicy.java" "$j/PortalTransitionPolicy.java" "$j/PortalContactPolicy.java" \
  "$j/ItemInteractionArgumentFence.java" "$j/PlacementCallbackFence.java" "$j/TypedPortalReaderPolicy.java" "$j/IdentityComponentSnapshot.java" "$j/TypedBoundaryPolicy.java" \
  "$root/client-mod/validation/typed-portals/TypedPortalPolicyChecks.java"
"$JAVA_HOME/bin/java" -cp "$out/classes" io.github.campione01.mineclientbridge.TypedPortalPolicyChecks
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$root/capability-runtime:$root/resident-controller:$root/capability-runtime/tests"
python -m unittest typed_portals.test_producers -v
python "$root/capability-runtime/tests/typed_portals/generate_intent_cases.py" "$out/intent-cases.json"

python -B "$root/client-mod/validation/typed-portals/check-argument-source.py"
