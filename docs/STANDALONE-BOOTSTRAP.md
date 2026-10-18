# Standalone source-runtime startup

Recovery TEST2.1 corrects the delivered Watchdog/Resident source dependency bootstrap exposed by the TEST2 live launch. The Watchdog reached its first reconciliation import and exited before MCP or any gameplay job. That original failed launch is retained.

The canonical Watchdog entry is `python -B SOURCE/defense-watchdog/watchdog.py run --queue QUEUE --control CONTROL --execution-policy request_only`. It resolves the shipped Resident source sibling and its Navigation dependency from the installed source tree. The canonical Resident entry is `PYTHONPATH=SOURCE/resident-controller python -B -m resident_controller ...`; it resolves the same Navigation sibling before loading the CLI. The packaged layouts navigation-controller and minecraft-navigation-controller are accepted. A missing required dependency fails explicitly; the resolver does not search the working directory or invent a fallback implementation.

The public Node entry remains `node SOURCE/client-mod/mcp/mineclient-bridge-mcp.mjs` with its existing operator-selected MINECLIENT_TOOLBOX_CONFIG. Its existing fixed child environment already supplies all delivered runtime siblings. No ambient sibling PYTHONPATH is needed for Watchdog or Node. Use PYTHONDONTWRITEBYTECODE=1 to keep the source pair immutable.

`defense-watchdog/test_standalone_bootstrap.py` starts the exact Watchdog command against a temporary offline-only mailbox, confirms normal STOP completion, checks canonical Resident startup and reconciliation/managed/defensive imports, and exercises the real public Node-to-Python catalog under a minimal parent environment. It has no game, endpoint, credential or live queue access. Native production sources and semantics are unchanged from TEST2.
