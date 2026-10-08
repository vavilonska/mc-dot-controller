#!/usr/bin/env bash
# Run by the owner in the same desktop terminal/network namespace as Minecraft Java.
# Explicit current URL + queue path are required; no launch, install, login or token discovery.
set -eu
cd -- "$(dirname -- "$0")"
if [ "$#" -lt 2 ]; then
  printf '%s\n' 'Usage: ./owner-start.sh http://127.0.0.1:VERIFIED_PORT /path/to/shared/mailbox [--token-file OWNER_SELECTED_PRIVATE_FILE]' >&2
  exit 2
fi
BASE_URL="$1"
QUEUE="$2"
shift 2
exec python3 -m resident_controller --queue "$QUEUE" start --base-url "$BASE_URL" "$@"
