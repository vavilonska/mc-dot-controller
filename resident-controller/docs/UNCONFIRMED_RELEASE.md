# Unconfirmed native input release: stop automatic continuation

A native action can terminate with `status: failed`, `reason:
input_release_unconfirmed` and `result.input_release_confirmed: false`. That raw
receipt is retained. It does not authorize another route merely because the
native registry is no longer running an action.

- Resident pauses and cancels queued semantic work when a terminal explicitly
  reports release unconfirmed. It publishes the original native receipt in the
  failed task result. Startup also preserves uncertainty from the last receipt.
- Watchdog latches a dedicated paused state before owner, environment or ranged
  priority work can dispatch again. A state/phase refresh cannot rearm it.
  The failure itself does not trigger another automatic cancellation/release.
  Read-only observation and an explicit operator stop remain permitted.
- Cursor blocks and preserves its original pending ID/route/checkpoint. Fresh
  observations, a helper reload or a different route are not release proof.
- Explicit true release evidence and older receipts that omit the new field
  retain their former behavior. A successful observation containing an old
  historical receipt is not misclassified as a new failed action task.

The latch requires operator handling; it is never cleared by observation timing.
This is an offline protocol guarantee, not proof of physical key state in a live
client. The synthetic chain tests use actual Resident, QueueClient, watchdog and
Navigator with a fake native bridge, and verify both no second dispatch and the
confirmed-release positive path. No Minecraft or network is used.
