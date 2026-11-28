#!/bin/bash
# Watch what macOS sees on USB, with timestamps. Reads IOKit only (ioreg): it never touches /Volumes, so a hung
# network mount cannot freeze it.
#   ./watch_usb.sh          until Ctrl+C
#   ./watch_usb.sh 120      for 120 seconds
cd "$(dirname "$0")" || exit 1
LOG="$PWD/usb_watch.log"
DURATION="${1:-0}"
say() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

sony_ids() {   # every Sony idProduct on USB, as hex, one per line (idProduct is DECIMAL in ioreg)
    ioreg -p IOUSB -w0 -l 2>/dev/null | awk '
        /"USB Vendor Name" = "Sony"/   { s = 1; next }
        s && /"idProduct" = [0-9]+/    { v = $3; gsub(/[^0-9]/, "", v); printf "%04x\n", v; s = 0 }
    '
}
describe() {
    case "$1" in
        0f47) echo "MASS STORAGE - the uninstall can run" ;;
        0d68) echo "HID / PC Remote - wrong mode (set USB -> Mass Storage)" ;;
        0336|02a9) echo "SERVICE MODE - the kit is mid-session" ;;
        033a|03e2) echo "UPDATER MODE - a firmware update is running" ;;
        *)    echo "Sony device, id not known to the kit" ;;
    esac
}

say "watch started; log $LOG"
start=$(date +%s); last=""; since=0
while :; do
    now=$(date +%s)
    if [ "$DURATION" != "0" ] && [ $((now - start)) -ge "$DURATION" ]; then say "finished after ${DURATION}s"; break; fi
    seen=$(sony_ids | sort -u | tr '\n' ' ')
    if [ -n "$seen" ]; then
        cur="$seen"
        if [ "$cur" != "$last" ]; then
            [ -n "$last" ] && say "  ^ ($last) gone after $((now - since))s"
            for id in $seen; do say "SONY $id  $(describe "$id")"; done
            last="$cur"; since=$now
        fi
    else
        if [ -n "$last" ]; then say "  ^ ($last) gone after $((now - since))s  - nothing from Sony on USB"; last=""; fi
    fi
    sleep 0.3
done
say "--- appearances this run ---"
grep "SONY " "$LOG" | tail -25
