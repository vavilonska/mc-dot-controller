# Optional jump criticals: verified Java 1.21.1 rules

Read-only verification used the locally cached official Minecraft Java 1.21.1
client/mappings and decompiled `net.minecraft.world.entity.player.Player`, not
another release's online guide.

The vanilla default requires:

- `getAttackStrengthScale(0.5F)` strictly greater than 0.9
- Positive `fallDistance`
- Off the ground; not climbing, in water, blinded, riding/passenger or sprinting
- A living-entity target

Moving forward is compatible; sprinting is not. An axe adds no separate critical
eligibility rule. Negative vertical velocity alone is not the vanilla predicate.
The eligible base attack component gets a 1.5 multiplier; the enchantment increment
is added afterward. The successful damage result gates the critical effects.

The underlying cooldown period is 20 divided by the attack-speed attribute, in
world ticks. The attack counter advances each tick and resets on a main-hand item
**type** change. Fixed wall-clock sword/axe intervals do not observe this state.

## Evidence anchors

Official cached client SHA-1: `30c73b1c5da787909b2f73340419fdf13b9def88`

Official cached mappings SHA-1: `2244b6f072256667bcd9a73df124d6c58de77992`

In the cached 1.21.1 decompile, `Player.java`:

- Lines 1141–1153: cooldown sample and threshold
- Lines 1164–1175: complete critical predicate and damage multiplier
- Lines 1193–1194 / 1249–1253: successful damage and critical effects
- Lines 1962–1967: attack-speed cooldown calculation
- Lines 305–309: counter ticking and main-hand type change

The locally cached NeoForge 21.1.255 `Player.java.patch` adds `CriticalHitEvent`;
listeners can override vanilla critical status and multiplier. Default eligibility
is not authoritative confirmation for every modded server.

## Why it is not implemented in this candidate

Current state exposes velocity, on-ground and active effects, but not direct
fall distance, sprinting, attack strength at 0.5, in-water, climbable or passenger
status. Blindness can be assessed from the effects list only if it is complete.
A sprint-release command or negative Y velocity is not proof of the missing facts.

A later observability change could expose those six values and check them before
an ordinary melee attempt. Even then, report eligibility/attempt separately from
server-confirmed critical damage. This candidate neither changes the mod nor
claims blind jump timing produces critical hits; ordinary melee closing comes first.
