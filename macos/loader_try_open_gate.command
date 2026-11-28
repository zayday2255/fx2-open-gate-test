#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 2. RAM only: brings the loader's files to the RAM disk and runs its helper once with the plan og2560 (the 3840x2560 open gate, 23.98p / 24p, applied as the kit's steps apply it). From a fresh power-on on STILL. Then loader_status, then MOVIE. A battery change undoes it.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_try_og2560 --go --firmware-shown "$FWV" "$@"
