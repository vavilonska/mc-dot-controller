> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Explicit idle pause acknowledgment

This control is limited to a request-only Watchdog that observed a clean GUI pause while it was armed, with no active gameplay owner, lease, uncertain input release, or handoff. It does not acknowledge arbitrary errors, deaths, transitions, lost observations, or interrupted jobs.

## Public use

1. Finish the current original job and confirm terminal cleanup. Pause through the normal game menu when needed.
2. Return to the same private single-player world and close the menu normally.
3. Call `mdc_catalog`. Read `runtime_binding_availability.session_ref` and `pause_acknowledgment`. Continue only when its exact version is `explicit-idle-pause-ack/1` and `eligible` is true.
4. Submit once through `mdc_job`:

```json
{"api_version":"mdc.toolbox/1","operation":"acknowledge_pause","request_id":"<new-request-id>","session_ref":"<catalog-session-ref>","pause_ref":"<catalog-pause-ref>","acknowledgment":"allow_new_requests_only_no_task_resume"}
```

5. Require a succeeded acknowledgment. A separately requested observation or job can then begin. No prior task is resumed. A known refusal permits another separately identified request only after its reported precondition changes. If the acknowledgment outcome is UNKNOWN, query its exact job status or explicitly reconcile its original acknowledgment receipt. Never replace or repeat an unknown request.

The control waits at most five seconds for two new, strictly increasing game-tick observations requested after the acknowledgment. Both must prove the same native session, world, dimension, player, integrated server and Resident identity, an unpaused closed menu, neutral input and no native ownership/quarantine. A final Resident/session/pending-command read is followed by a same-object, epoch, context, uncertainty and deadline fence. Success advances the Watchdog epoch once and admits only fresh future requests. It neither posts a native action nor installs a gameplay lease.

The request and exact Watchdog receipt are durable. Duplicate public IDs return the original record. Shutdown performs only an exact receipt lookup; an unresolved acknowledgment remains UNKNOWN. Reconciliation of this control reads only its original control receipt and does not settle any gameplay job. Existing UNKNOWN gameplay history and its owner barriers remain intact.

The original 2.6 process has no such API. Its first cold upgrade requires the existing clean shutdown and same-world backup procedure. Subsequent eligible optimization pauses can be acknowledged in the same 2.7 process. No hotpatch or journal edit is supported.
