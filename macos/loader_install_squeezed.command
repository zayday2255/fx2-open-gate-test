#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 3 with the plan squeeze (the squeezed open gate). WRITES FLASH. Undo: loader_uninstall.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. WRITES THE CAMERA'S FLASH: a battery change does not undo it.
cd "$(dirname "$0")" || exit 1
echo "THIS CHANGES THE CAMERA'S FLASH. A battery change does not undo it; loader_uninstall does."
read -r -p "Type FLASH to go on: " OK
[ "$OK" = FLASH ] || { echo "Nothing was sent."; read -r -p "Press Return to close. "; exit 1; }
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_install_squeeze --go --writes-flash --firmware-shown "$FWV" "$@"
