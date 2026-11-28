#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER: read-only: the helper's log and the whole result of every step of its last run, saved in the session folder (the folder to send when a step did not do what SDBOOT.md says).
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_report --go --firmware-shown "$FWV" "$@"
