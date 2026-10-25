#!/usr/bin/env bash
set -euo pipefail
B=/workspace/scratch/5f333e5a575b
N="$B/MDC-RECOVERY-LIVE-F1220-20261022"
umask 077
exec 9>"$N/ordinary-idle-guard.lock"
flock -n 9 || { echo 'REFUSED_NO_INPUT: another ordinary helper owns input'; exit 2; }
exec python3 "$(dirname "$0")/launch-from-room.py" --arm "$@"
