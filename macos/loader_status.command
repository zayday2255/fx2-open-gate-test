#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER: read-only status: what is installed, the plan, and what the helper did at its last run.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_status --go --firmware-shown "$FWV" "$@"
