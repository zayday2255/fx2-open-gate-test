#!/bin/bash
# FX2 (firmware 1.01) LOCAL one-shot launcher, ONE-CONNECTION version: the 3840x2560 open gate (L13 + H5 + L16 + L19 + S16).
# The read-only check and all five pinned libraries in a single service-mode connection (fx2_batch.py): nothing is written unless
# the check in that same connection says READY for an FX2 1.01, and the camera never drops back to a USB drive in between. Only the Mac password is asked. If this ever misbehaves, open_gate_3840x2560_test.command does the same
# steps one connection at a time.
# Before: switch on STILL, fresh power-on (battery out 10 s), XAVC HS/S 4K 24p + SteadyShot Off set on MOVIE, USB Connection Mode = Mass Storage.
# After: unplug, set MOVIE, shoot. Do not power off (that clears it). WRITES camera memory only; a cold boot returns it to stock.
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
# Spotlight indexing the camera's card can block the unmount (seen 2026-11-26): a marker file tells it never to index the FX2's card.
for v in /Volumes/*; do [ -d "$v/PRIVATE/M4ROOT" ] && touch "$v/.metadata_never_index" 2>/dev/null; done
"$PY" -I -B "$TOOLS/fx2_batch.py" "$PLAN" --dry-run >/dev/null || { echo "!! The offline checks of the batch failed. Nothing was sent. Use open_gate_3840x2560_test.command."; done_ 1; }
echo "Open gate $LABEL (one connection, check included): camera on STILL, fresh power-on (battery out), USB in. Your Mac password, once:"
sudo /bin/bash -c '
  trap : INT
  PY=$1; TOOLS=$2; PRIVATE=$3; PLAN=$4
  for v in /Volumes/*; do [ -d "$v/PRIVATE/M4ROOT" ] && mdutil -i off "$v" >/dev/null 2>&1; done
  "$PY" -I -B "$TOOLS/fx2_batch.py" "$PLAN" --go --firmware-shown 1.01
  status=$?
  [ -d "$PRIVATE" ] && chown -R "$SUDO_UID:$SUDO_GID" "$PRIVATE"
  exit $status' go "$PY" "$TOOLS" "$PRIVATE" "$PLAN"
status=$?
echo
[ $status -eq 0 ] && echo ">>> Done. Unplug, set MOVIE, shoot (4K 24p on NTSC, 25p on PAL; SteadyShot Off). Do not power off." || echo ">>> Stopped (status $status). See the lines above."
done_ $status
