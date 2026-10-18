> Publication context (2026-10-18): Recovery 2.5 source and its version-qualified acceptance are now recorded in [the current publication note](docs/recovery-2026-10-18/README.md). The text below is the historical candidate/change record; its unpushed or live-pending statements describe that earlier checkpoint. Historical failures and UNKNOWN outcomes remain unchanged.

# Recovery TEST2.4 corrections

This private single-player pair adds the independently reviewed Python-only exact-terminal cancellation-race correction to frozen TEST2.3. Code remains unpushed. All 198 native Java sources, both Mixin configurations and all 469 compiled production classes are byte-identical to the accepted TEST2.3 build; they are verified and reused, not newly compiled.

A native inventory click can finish and release its input immediately before its public cancellation reaches the gateway. Only a new closed, exact original/owner/session/context/epoch-bound proof can acknowledge that no native cancellation was dispatched. The overall transfer stops with incomplete semantic verification and still requires fresh neutral cleanup. The proof cannot settle historical UNKNOWN, a missing or unsafe original, a replaced owner, or a possibly queued cancel. No retry, cursor rollback, automatic recovery or timing relaxation is added.

After confirmed cleanup, request a fresh authoritative full-menu observation, then submit recover_cursor separately with that observation's current menu/screen/cursor references. Never use an old step's carried count. Duplicate original request IDs return the retained outcome without another click.

TEST2.3 separately passed GUI-pause cleanup, including an actual renewal refusal race, and managed walking arrival plus in-flight cancellation. Its cursor case exposed this cancellation race and remained UNKNOWN; subsequent vanilla close and cold save conserved 15 player dirt plus 1 chest dirt. That is not recover_cursor acceptance. Other version-specific evidence is in the release's live matrix. Fresh TEST2.4 cancellation and recovery acceptance is pending at packaging.

Use RECOVERY-TEST2-QUICKSTART.md and the exact release/operator handoff. Cold-stop and verify the paired source and JAR, use a fresh test context and new intent IDs, preserve the original world and every old UNKNOWN receipt. Attached protection remains limited to the exact same-owner native follow_path/combat_entity action; managed walking is not attached-protected.
