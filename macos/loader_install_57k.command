#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER, STEP 3 with the 5.7K plan. WRITES FLASH: installs the loader with the plan og57 (5760x3840, 300 Mbps on the 100M and higher settings, 23.98p / 24p) at every power-on on STILL with an SD card in. Only after steps 1 and 2 worked. Undo: loader_uninstall.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. WRITES THE CAMERA'S FLASH: a battery change does not undo it.
# The SD card is the on/off switch: with the card out, a power-on applies nothing.
cd "$(dirname "$0")" || exit 1
echo "THIS CHANGES THE CAMERA'S FLASH. A battery change does not undo it; loader_uninstall does."
read -r -p "Type FLASH to go on: " OK
[ "$OK" = FLASH ] || { echo "Nothing was sent."; read -r -p "Press Return to close. "; exit 1; }
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_install_og57 --go --writes-flash --firmware-shown "$FWV" "$@"
