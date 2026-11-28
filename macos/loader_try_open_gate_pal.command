#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 2 for a PAL-set FX2 (25p). RAM only, as loader_try_open_gate.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_try_og2560pal --go --firmware-shown "$FWV" "$@"
