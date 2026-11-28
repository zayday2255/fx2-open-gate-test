#!/bin/bash
# Hunt for the FX2 in SERVICE mode (054c:0336) and run the uninstall the moment it appears (LOCAL, 2026-11-28).
#
# Why 0336: init2 calls setup_senser() BEFORE bootin.elf, reading /setting/sen/smode. When the camera app dies (black screen, no
# backlight) the kernel can still be alive with sen.elf running, and that is the USB service device the kit's delete path uses.
# Service mode needs no mass-storage enumeration and no card driver - so the fork storm, which kills the mass-storage handshake,
# may not matter here.
#
# It watches IOKit (ioreg) only, so a hung mount cannot freeze it, and when 0336 appears it runs the kit's own one-step uninstall
# (W41), which deletes /etc/ld.so.preload FIRST and needs nothing else to be intact.
#
#   sudo ./service_mode_watch.sh            watch until Ctrl+C (asks for FLASH first)
#   sudo ./service_mode_watch.sh 1800       for 30 minutes
cd "$(dirname "$0")" || exit 1
PY="$PWD/.venv/bin/python"
TOOLS="$PWD/../windows/tools/camera_tests/CT6_memory_read_check"
PRIVATE="$PWD/../windows/camera_private"
LOG="$PWD/service_watch.log"
DURATION="${1:-0}"

say() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

# every Sony product id on USB, as 4 hex digits. libusb, not ioreg: ioreg prints idProduct BEFORE the vendor name inside a
# device's property block, so a "wait for vendor, then read idProduct" awk never matches (found 2026-11-28 the hard way).
sony_ids() {
    "$PY" -c "
import usb.core
try:
    print(' '.join(sorted({'%04x' % d.idProduct for d in usb.core.find(find_all=True, idVendor=0x054C)})))
except Exception:
    pass
" 2>/dev/null
}

echo "THIS WILL REMOVE THE START-UP LOADER FROM THE CAMERA'S FLASH (it only removes)."
read -r -p "Type FLASH to go on: " OK
[ "$OK" = FLASH ] || { echo "Nothing was sent."; exit 1; }

say "service-mode watch started; log $LOG"
say "leave the camera powered and plugged in; power-cycling is fine, do not unplug the cable"
say "waiting for 054c:0336 (service mode) ..."

start=$(date +%s)
attempts=0
while :; do
    now=$(date +%s)
    if [ "$DURATION" != "0" ] && [ $((now - start)) -ge "$DURATION" ]; then
        say "finished after ${DURATION}s; $attempts appearance(s) seen"
        break
    fi
    ids=$(sony_ids)
    case " $ids " in
        *" 0336 "*|*" 02a9 "*)
            attempts=$((attempts + 1))
            say "SERVICE MODE $ids -> running the uninstall (attempt $attempts)"
            before=$(ls -1d "$PRIVATE"/CT6_*_fx2_batch_loader_uninstall 2>/dev/null | wc -l | tr -d ' ')
            "$PY" -I -B "$TOOLS/fx2_batch.py" loader_uninstall --go --writes-flash --firmware-shown 1.01 >>"$LOG" 2>&1
            after=$(ls -1d "$PRIVATE"/CT6_*_fx2_batch_loader_uninstall 2>/dev/null | wc -l | tr -d ' ')
            if [ "$after" -gt "$before" ]; then
                newest=$(ls -1d "$PRIVATE"/CT6_*_fx2_batch_loader_uninstall | tail -1)
                if grep -q '"outcome": "DONE"' "$newest"/manifest.json 2>/dev/null \
                   || grep -q "DONE: /etc/ld.so.preload and /etc/fx2boot are gone" "$newest"/W41_readcheck_result.txt 2>/dev/null; then
                    say "SUCCESS: the loader is uninstalled. Power-cycle the camera; it should boot normally."
                    say "session folder: $newest"
                    exit 0
                fi
                say "the session ran but did not report DONE; see $newest"
            fi
            sleep 2
            ;;
        *)
            # not in service mode; note any change of identity so the log shows what the camera is doing
            [ "$ids" != "$last_ids" ] && { say "usb now: ${ids:-nothing from Sony}"; last_ids="$ids"; }
            ;;
    esac
    sleep 0.3
done

say "--- what was seen ---"
grep -E "usb now|SERVICE MODE|SUCCESS" "$LOG" | tail -20
