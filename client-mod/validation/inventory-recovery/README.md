# Inventory recovery offline gate

Use the existing pinned JDK 21 and compiler-only classpath from movement-t13. Compile all production sources first with a single JVM capped at 384 MiB, no annotation processing and an empty implicit source path. Do not download dependencies or launch a game.

1. Run `generate_wire.py generate NEW_INPUT_DIRECTORY`.
2. Compile `InventoryRecoveryWireChecks.java` against the freshly compiled production classes.
3. Run `InventoryRecoveryWireChecks INPUT_DIRECTORY NEW_OUTPUT_DIRECTORY` with a JVM capped at 128 MiB.
4. Run `generate_wire.py verify OUTPUT_DIRECTORY` to consume the actual Java HTTP-codec bytes with the production Resident validator.

The Java gate executes the unchanged production request parser and HTTP encoder. It checks four exact pickup/storage requests, 88 malformed forms, and preservation of legacy guarded clicks. The Python consumer rejects 32 re-sealed altered state bindings, independently of the command digest. Captured world/menu/inventory facts are synthetic; this is not live click execution or server acknowledgement evidence.

The Python suite `test_inventory_recovery` separately covers real durable Runtime receipt handling, delayed semantic observations, unknown and failed actions, unconfirmed release and no replay. `test_inventory_recovery_chain` uses the actual public service, owner, watchdog and Resident chain with a synthetic native endpoint. The Node `toolbox-inventory-recovery-test.mjs` runs that same chain in a subprocess through the production MCP adapter.

`InventoryRecoveryBoundaryChecks` executes the dependency-free production boundary
with synthetic callback replacement/reentrancy faults (1,400 assertions). The
registered production click/send mixins also have a bytecode-only transformation
gate in the associated result bundle: 16 registered mixins, nine actual target
classes, seven seam-order checks, and a deliberately missing `clicked` injection
seam rejected. This transforms real pinned class bytes without defining or
initializing Minecraft classes; it is not live native callback acceptance.
