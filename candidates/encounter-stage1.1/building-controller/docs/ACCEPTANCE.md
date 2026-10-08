# Future placement acceptance boundary

Current acceptance is **source and offline planning only**. There is no runtime
placement integration. Do not wire proposed placements straight into game input.
An adapter with only a right-click button is not an accepted placement primitive.

Before any live build, a separate, authorized implementation must establish:

1. Movement and turning primitives are independently accepted, bounded, neutral
   on completion/cancel/error, and stop on identity changes, user input or UI
2. A real single-placement primitive has an explicit target/face, finite duration,
   expected item, world/player identity, input-release guarantees and observable
   postconditions. No breaking, automatic retries or replacement fallback
3. Source and game version assumptions match; supported palette properties and
   actual block-item mappings are verified. Intent is still constrained to the
   reviewed explicit region and blueprint, not inferred from inventory contents
4. Fresh terrain/state/inventory/entity samples cover the target, support, swept
   work position and path. The client's perception and chunk visibility limits are
   checked, rather than trusting archive times or an empty/truncated entity list
5. Safe stand positions, headroom, safe floor, reach and unobstructed hit-face
   visibility exist for every proposed block. A geometric support chain does not
   prove any of these. Planned future blocks cannot be navigated on until observed
6. Inventory selection and available materials are verified immediately before
   the primitive; selected item, actual hit target and placement state agree
7. One placement is followed by release and observation. Only the expected newly
   placed cell advances the plan. Any damage, fluid, entity, conflict, unknown,
   world change, unexpected placement or stale observation stops the entire run
8. A reviewed recovery path stops safely. It does not break a mistaken block,
   replace structures, craft/gather materials, resume automatically, or edit saves

The initial acceptance should use a disposable backed-up test world and a single
explicitly approved block. Successful tests there are not broad authorization to
build or alter a user's current survival world.

## Regression intent

The suite includes positive floor/wall proposals and prior-index dependencies;
existing-correct skipping; whole-plan suppression for conflicts; unknown/fluid/
hazard/malformed cells; entity coverage/truncation/overlap; main-inventory limits;
page ordering/mixed generations/ticks/budgets; CLI JSON/errors/exclusive output;
and sanitized actual bridge capture parsing.

Independent review identified and fixed large-number overflow, contradictory air
collision evidence, false loaded support outside the supported world height, and
a float masquerading as the integer inventory-total field. These have regression
tests. Passing them does not remove the live acceptance boundary above.
