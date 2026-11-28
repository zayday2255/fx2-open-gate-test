#!/bin/bash
# Shared by the .command launchers: runs the Windows kit's own tools (fx2_run.py or fx2_apply.py) with this folder's Python.
#   run.sh run <fx2_run.py arguments>      run.sh apply <fx2_apply.py arguments>      run.sh batch <fx2_batch.py arguments>
# macOS keeps its own mass-storage driver on the camera, and only root may take the camera over from it, so a live
# run goes through sudo. --dry-run and --selftest send nothing and run without it.
cd "$(dirname "$0")" || exit 1
PY="$PWD/.venv/bin/python"
TOOLS="$PWD/../windows/tools/camera_tests/CT6_memory_read_check"
PRIVATE="$PWD/../windows/camera_private"
close() { echo; read -r -p "Press Return to close. "; exit "$1"; }
case "$1" in
  run) SCRIPT="$TOOLS/fx2_run.py" ;;
  apply) SCRIPT="$TOOLS/fx2_apply.py" ;;
  batch) SCRIPT="$TOOLS/fx2_batch.py" ;;
  *) echo "run.sh: first argument must be run, apply or batch"; close 2 ;;
esac
shift
if [ ! -x "$PY" ]; then
  echo "Python environment missing: run setup.command first."
  close 1
fi
case " $* " in
  *" --dry-run "*|*" --selftest "*) "$PY" -I -B "$SCRIPT" "$@"; close $? ;;
esac
echo "macOS asks for your password: taking the camera over from its own USB driver needs admin rights."
# The sessions are saved as root; the same root shell gives them back to you afterwards, so a run longer than
# sudo's 5-minute grace period doesn't ask for the password a second time. `trap : INT` keeps that shell alive
# through Ctrl+C (the child still stops), so the sessions are given back then too.
sudo /bin/bash -c 'trap : INT; private=$1; shift; "$@"; status=$?
  [ -d "$private" ] && chown -R "$SUDO_UID:$SUDO_GID" "$private"; exit $status' run "$PRIVATE" "$PY" -I -B "$SCRIPT" "$@"
close $?
