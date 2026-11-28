#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 1. RAM only and READS only: brings the loader's files to the camera's RAM disk and runs its helper once with the plan 'check' (it reads the coprocessor and encoder sites from outside the camera application). Then run loader_status. A battery change removes everything.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_try_check --go --firmware-shown "$FWV" "$@"
