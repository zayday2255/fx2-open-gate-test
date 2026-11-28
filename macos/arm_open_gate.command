#!/bin/bash
# FX2 open gate: ARM, then plug in (LOCAL, 2026-11-26). Asks your Mac password once, then waits up to 15 minutes for the FX2
# and applies the 3840x2560 open gate by itself the moment it connects (read-only check + L13 H5 L16 L19 S16 in one connection).
# It runs in this Terminal window, as the launchers do: macOS refuses to let a background (launchd) job take the camera from its
# USB driver (claim interface: Other error, seen twice 2026-11-26), and a Terminal sudo works.
# Nothing is written unless the check in that same connection says READY for an ILME-FX2 1.01. RAM only: a battery pull undoes it.
cd "$(dirname "$0")" || exit 1
PY="$PWD/.venv/bin/python"
TOOLS="$PWD/../windows/tools/camera_tests/CT6_memory_read_check"
PRIVATE="$PWD/../windows/camera_private"
PLAN="${FX2_PLAN:-og2560}"                     # og2560 = 3840x2560, og57 = 5.7K (5760x3840); the _57 launchers set it
# The menu bar app's "1.5x anamorphic preview" checkbox: with this file present the plan also runs A16 (De-Squeeze 1.3x -> 2.25:1)
[ -f "$HOME/.fx2_opengate_anamorphic" ] && case "$PLAN" in og2560|og57) PLAN="${PLAN}a";; esac
case "$PLAN" in og2560) LABEL="3840x2560";; og57) LABEL="5.7K (5760x3840)";; og2560a) LABEL="3840x2560 + 1.5x anamorphic preview";;
  og57a) LABEL="5.7K (5760x3840) + 1.5x anamorphic preview";; *) echo "Unknown plan $PLAN"; exit 1;; esac
done_() { echo; read -r -p "Press Return to close. "; exit "$1"; }
[ -x "$PY" ] || { echo "Python environment missing: run setup.command first."; done_ 1; }
"$PY" -I -B "$TOOLS/fx2_batch.py" "$PLAN" --dry-run >/dev/null || { echo "!! The offline checks failed. Nothing was sent."; done_ 1; }
echo "Arming the FX2 open gate ($LABEL). Your Mac password, once:"
sudo /bin/bash -c '
  trap : INT
  PY=$1; TOOLS=$2; PRIVATE=$3; PLAN=$4; U=$SUDO_USER
  note() { sudo -u "$U" /usr/bin/osascript -e "display notification \"$1\" with title \"FX2 open gate\" sound name \"$2\"" >/dev/null 2>&1; }
  fx2() { /usr/sbin/ioreg -p IOUSB -l -w0 | /usr/bin/awk "/\"idVendor\" = 1356/{v=1} /\"idProduct\" = 3911/{p=1} END{exit !(v&&p)}"; }
  if fx2; then
    echo; echo "!! The FX2 is already plugged in. Unplug it, then battery out 10 s, dial on STILL, power on, and plug it in again."
    while fx2; do sleep 1; done
  fi
  echo; echo "ARMED. Now: battery out 10 seconds, dial on STILL, power on, plug in USB (pick Mass Storage if asked)."
  note "Armed. Plug in the FX2 (STILL, after a battery pull)." "Tink"
  found=0
  for _ in $(seq 450); do fx2 && { found=1; break; }; sleep 2; done
  if [ $found -ne 1 ]; then echo "No FX2 in 15 minutes. Disarmed."; note "No FX2 in 15 minutes. Disarmed." "Basso"; exit 1; fi
  echo "FX2 connected. Applying (about 15 seconds). Do not unplug."
  note "FX2 found. Applying, about 15 seconds. Do not unplug." "Pop"
  sleep 3
  for v in /Volumes/*; do
    if [ -d "$v/PRIVATE/M4ROOT" ]; then touch "$v/.metadata_never_index" 2>/dev/null; /usr/bin/mdutil -i off "$v" >/dev/null 2>&1; fi
  done
  "$PY" -I -B "$TOOLS/fx2_batch.py" "$PLAN" --go --firmware-shown 1.01
  status=$?
  [ -d "$PRIVATE" ] && chown -R "$SUDO_UID:$SUDO_GID" "$PRIVATE"
  if [ $status -eq 0 ]; then note "Done. Unplug, set MOVIE, shoot. Do not power off." "Glass"; else note "Stopped. Nothing more was written. Pull the battery and arm again." "Basso"; fi
  exit $status' go "$PY" "$TOOLS" "$PRIVATE" "$PLAN"
status=$?
echo
[ $status -eq 0 ] && echo ">>> Done. Unplug, set MOVIE, shoot (4K 24p on NTSC, 25p on PAL; SteadyShot Off). Do not power off." || echo ">>> Stopped (status $status). See the lines above."
done_ $status
