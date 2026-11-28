#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER: UNINSTALL, WAIT AND RETRY (LOCAL, 2026-11-28). For a camera that restarts by itself.
# Asks FLASH and your Mac password once, then for up to 20 minutes: each time the FX2 shows up as a USB drive it lets the
# connection settle and runs the kit's own loader_uninstall plan (one step, W41, about 2 seconds), and goes on trying until a
# session ends "completed". Why: the plain launcher pounces the instant the drive appears and gives up after one try
# (2026-11-28 08:40Z: "macOS did not let go of the camera's mass-storage driver (No such device)").
# The batch tool exits 0 even when it stops early, so success is read from the session's own manifest, not the exit status.
# CHANGES THE CAMERA'S FLASH (removes /etc/ld.so.preload first, then the loader's folder). It only removes.
cd "$(dirname "$0")" || exit 1
PY="$PWD/.venv/bin/python"
TOOLS="$PWD/../windows/tools/camera_tests/CT6_memory_read_check"
PRIVATE="$PWD/../windows/camera_private"
done_() { echo; read -r -p "Press Return to close. "; exit "$1"; }
[ -x "$PY" ] || { echo "Python environment missing: run setup.command first."; done_ 1; }
echo "THIS CHANGES THE CAMERA'S FLASH: it removes the start-up loader. It keeps trying for 20 minutes."
read -r -p "Type FLASH to go on: " OK
[ "$OK" = FLASH ] || { echo "Nothing was sent."; done_ 1; }
"$PY" -I -B "$TOOLS/fx2_batch.py" loader_uninstall --dry-run >/dev/null || { echo "!! The offline checks failed. Nothing was sent."; done_ 1; }
echo "Your Mac password, once:"
sudo /bin/bash -c '
  stop=
  trap "stop=1" INT
  PY=$1; TOOLS=$2; PRIVATE=$3
  fx2() { /usr/sbin/ioreg -p IOUSB -l -w0 | /usr/bin/awk "/\"idVendor\" = 1356/{v=1} /\"idProduct\" = 3911/{p=1} END{exit !(v&&p)}"; }
  newest() { ls -1d "$PRIVATE"/CT6_*_fx2_batch_loader_uninstall 2>/dev/null | tail -1; }
  give_back() { [ -d "$PRIVATE" ] && chown -R "$SUDO_UID:$SUDO_GID" "$PRIVATE"; }
  echo
  echo "WAITING for the FX2. Camera: no card, dial on STILL, power on, USB in, pick Mass Storage if it asks."
  echo "Leave it plugged in. Ctrl+C stops."
  end=$(( $(date +%s) + 1200 )); n=0; won=0
  while [ "$(date +%s)" -lt "$end" ] && [ -z "$stop" ]; do
    if ! fx2; then sleep 0.5; continue; fi
    n=$((n + 1))
    # odd tries let macOS finish with the new drive first (3 s); even tries go sooner, in case the camera does not stay up that long
    if [ $((n % 2)) -eq 1 ]; then settle=3; else settle=1; fi
    echo; echo "[$(date +%H:%M:%S)] FX2 is a USB drive: try $n, settling $settle s"
    sleep $settle
    if ! fx2; then echo "  it went away before the try (the camera restarted?). Waiting for it again."; continue; fi
    before=$(newest)
    "$PY" -I -B "$TOOLS/fx2_batch.py" loader_uninstall --go --writes-flash --firmware-shown 1.01
    after=$(newest)
    if [ -n "$after" ] && [ "$after" != "$before" ] && grep -q "\"status\": \"completed\"" "$after/manifest.json" 2>/dev/null; then won=1; break; fi
    echo "  try $n did not finish. Waiting for the camera again."
    sleep 1
  done
  give_back
  if [ $won -eq 1 ]; then
    echo; echo ">>> UNINSTALLED on try $n. Session: $after"
    exit 0
  fi
  echo; echo ">>> NOT uninstalled after $n tries (stopped, or 20 minutes passed). Sessions are in $PRIVATE"
  exit 1' go "$PY" "$TOOLS" "$PRIVATE"
status=$?
[ $status -eq 0 ] && echo "Now: battery out 10 seconds, then run loader_status.command to confirm nothing is installed."
done_ $status
