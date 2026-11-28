#!/bin/bash
# FX2: tell me when the camera is up LONG ENOUGH to act (LOCAL, 2026-11-28).
#
# Measured on the camera (service_watch.log): the camera's USB appearances are bursty, not a fixed loop -
# median 3 s, but one ran 79 s and another 16 s. A long appearance is the only chance to change a setting
# (USB Connection Mode) or run a step, and the uninstall needs ~5 s.
#
# This prints a line the moment an appearance has lasted LONGER than the threshold, and keeps printing
# while it stays up, so you know when to move.
#
#   ./window_watch.sh            threshold 8 s (enough for the uninstaller)
#   ./window_watch.sh 20         only shout when it has been up 20 s (enough to change a setting calmly)
cd "$(dirname "$0")" || exit 1
PY="$PWD/.venv/bin/python"
NEED="${1:-8}"
LOG="$PWD/window_watch.log"

say() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

sony_ids() {
    "$PY" -c "
import usb.core
try:
    print(' '.join(sorted({'%04x' % d.idProduct for d in usb.core.find(find_all=True, idVendor=0x054C)})))
except Exception:
    pass
" 2>/dev/null
}

say "watching; shouting when the camera stays up for ${NEED}s or more"
last=""; since=0; shouted=0
while :; do
    now=$(date +%s)
    ids=$(sony_ids)
    if [ -n "$ids" ]; then
        if [ "$ids" != "$last" ]; then
            last="$ids"; since=$now; shouted=0
            say "appeared: $ids"
        fi
        held=$((now - since))
        if [ "$held" -ge "$NEED" ] && [ "$shouted" = 0 ]; then
            shouted=1
            say "*** WINDOW OPEN: $ids has been up ${held}s - GO NOW ***"
            case " $ids " in
                *" 0f47 "*) say "    mass storage: run ./loader_uninstall.command" ;;
                *" 0336 "*|*" 02a9 "*) say "    service mode: run ./loader_uninstall.command" ;;
                *" 0d68 "*|*" 096f "*) say "    PC Remote only: change USB Connection Mode to Mass Storage in the menu, then let it sit" ;;
            esac
        fi
        if [ "$shouted" = 1 ] && [ "$held" -ge $((NEED + 10)) ] && [ $((held % 10)) -eq 0 ]; then
            say "    still up: ${held}s"
        fi
    else
        if [ -n "$last" ]; then
            say "gone after $((now - since))s ($last)"
            last=""; shouted=0
        fi
    fi
    sleep 0.25
done
