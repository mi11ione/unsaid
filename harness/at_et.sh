#!/bin/bash
# at_et.sh "YYYY-MM-DD HH:MM" <script> [args]: wait on the wall clock (fires on wake if the Mac slept), check the disk,
# then run the script under caffeinate. Logs go wherever the caller redirects.
T=$(TZ=America/New_York date -j -f "%Y-%m-%d %H:%M" "$1" +%s) || exit 1; shift
echo "[at_et] waiting until $(date -r $T) for $*"
until [ "$(date +%s)" -ge "$T" ]; do sleep 60; done
free=$(df -g "$(dirname "$0")" | awk 'NR==2{print $4}')
if [ "${free:-0}" -lt 3 ]; then echo "[at_et] ABORT: ${free} GB free < 3 GB; not starting $*"; exit 1; fi
echo "[at_et] start $(date) ($free GB free): $*"
exec caffeinate -i "$@"
