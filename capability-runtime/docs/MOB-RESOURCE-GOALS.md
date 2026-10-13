# Species-specific combat and mob resources

`discover_mobs`, `defeat_nearby` and `hunt_resource` choose from complete current observations without caller-supplied UUIDs or coordinates. The hunt supports actual inventory totals for Ender pearls, blaze rods, string and gunpowder. Each kill requires health/death evidence; each resource goal separately requires stable inventory gain. Zero-drop kills consume the original target budget and do not count as resource success.

The policies are deliberately species-specific:

- Spider: ordinary verified melee/ranged target actions with dry footing, health and collateral guards.
- Cave spider: ranged stand-off, no current poison; no blind melee fallback.
- Creeper: ranged stand-off of at least12 blocks, or16 when charged; observed vanilla fuse/explosion facts, no ignition or swelling. A newly active fuse interrupts the action.
- Enderman: melee from a freshly observed dry full-cube3×3 roof at player feet+2, centered supported stance and no unrelated active threats. Native callbacks independently recheck the roof. The hunt searches for an observed suitable shelter; it does not currently construct one. Teleport/disappearance is not death.
- Blaze with sufficient actual Fire Resistance: ranged stand-off and remaining-effect checks.
- First-blaze shield strategy: actual offhand shield with at least64 durability, health above18, isolated stationary stand at16–32 blocks. One native18–20 second lifecycle first raises the shield, observes a real charged-to-uncharged volley transition with cleared fireballs, draws/releases exactly one arrow, then raises the shield again. Successful completion requires observed blocking, at least20 post-cover ticks, cleared charge/projectile risk and normal input release. It does not infer an unseen cooldown or retry an aborted bow. Missing cycle, changed equipment, unsafe incoming projectile, new damage or uncertain item-use release stops the goal.

Exact native living-target witnesses retain the same UUID/entity/type, initial/minimum observed health, actual death flag and observation tick. They can prove death after the render entity expires, but an absent entity or old receipt cannot. Runtime still requires exact submitted-action correlation and two strictly later same-action samples.

Search, movement, targets, native mutations and time remain bounded. No guarantee is made that a loaded region contains a fortress, a safe Enderman shelter or sufficient drops. Piglin barter, arbitrary neutral-mob farming and proven mixed-hostile survival are outside these tactics. Existing zombie/skeleton combat remains available separately. Offline synthetic endpoint, adapter, native policy and loader tests do not establish real gameplay survival; live cases need their own bounded acceptance.
