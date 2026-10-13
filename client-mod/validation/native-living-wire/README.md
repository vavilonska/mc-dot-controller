# Native living production-wire validation

This offline emitter sends labelled synthetic immutable `NativeLivingSnapshot` inputs through the final production JAR's `NativeLivingSnapshot.json` and exact HTTP encoder `BridgeJson.toJson`. It does not start Minecraft, load a world, deploy, or infer live acceptance.

Run with the existing pinned Gson/JDK and final built mod:

    bash run.sh CLIENT_MOD_ROOT EXISTING_GSON_JAR JDK21_HOME BUILT_CLIENT_JAR

Only `NativeLivingWire.java` is compiled. An empty source path prevents implicit production-source compilation. The final production JAR is first on both classpaths, and the emitter checks the production classes' runtime CodeSource against that exact JAR. `.build/INPUTS.json` records source, emitter, dependency, compiler/runtime executable and production-JAR hashes, classpath, generated class and output hash.

`.build/native-wire.json` is an array of `{name, response_json}`. `response_json` is the exact production-encoded `/control/state` root shape, not a reserialized Python fixture. The consumer must parse it directly and pass it unchanged to the existing ambient classifier. Cases include both known nulls, actual current/persistent target values independently and together, unavailable/expired sources, deliberate missing contract fields, unrelated null omission, and complete multiple-row input with a Bee, Sheep and empty ordinary Boat. Removed fields model corrupt/incomplete transport; the emitter never repairs them. Native null/target fields come from production snapshot serialization rather than handwritten dictionaries.

Synthetic context is `("synthetic-native-wire-world", "minecraft:overworld", "00000000-0000-4000-8000-000000000001", "synthetic-native-wire-session")`. Player position is `(0,64,0)`, scan radius is 48, and protected box `(-6,63,-6)` to `(4,69,4)` is fully covered. `known_null`, `unrelated_nulls`, and `multiple_rows` should pass the strict classifier; all other cases should reject. No classifier relaxation is required or authorized.

`NativeLivingWireTest` covers heterogeneous array shape/order, exact-path boundaries, unrelated null omission at all depths, actual targets, unknown/missing fields, repeat stability, and no input mutation through the production encoder and parse. The genuine FML `NativeLivingObservationLoaderTest` also verifies actual vanilla Bee accessors through the snapshot and encoder. Retain the pre-fix failing regression and final XML/logs separately.
