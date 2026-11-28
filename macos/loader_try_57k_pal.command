#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 2 with the 5.7K plan, for a camera set to PAL (25p). RAM only, as loader_try_57k.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_try_og57pal --go --firmware-shown "$FWV" "$@"
