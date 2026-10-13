# Additive shulker-box recipe

The only production change is the exact frozen-v18 RECIPES row for a vertical shulker_shell/chest/shulker_shell recipe producing one minecraft:shulker_box. Every current main function body is retained byte-for-byte, including required game time, nondecreasing observations, explicit typed pending count, and two strictly later distinct matching samples for final inventory and grid/cursor cleanup.

The existing independent fixture adds the expected H/B/H shape, shell/chest stock and symbols, and shulker_box to the 2x2 rejection cases. All previous assertion expressions remain unchanged. New tests cover two later samples, duplicate ticks, a matching sample followed by rollback, uncertain output after possible effect, time regression, missing pending metadata, and insufficient shells before any click. Each applicable failure preserves one output retrieval and no replay.

These checks use a synthetic queue, not Minecraft crafting or container lifecycle evidence. The separate seven real NeoForge container gates remain unmet. Crafting is explicitly invoked, preserves the original uncertain request ID, and does not automatically clean up, retry, take over inputs, or open a crafting menu. World pause, server confirmation and new deployment are not claimed.
