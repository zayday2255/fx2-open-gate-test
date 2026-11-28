#!/bin/bash
# FX2 (firmware 1.01): START-UP LOADER: UNINSTALL. Removes /etc/ld.so.preload first, then the loader's folder and what the research branch left. Changes flash (removes files). Run it before a firmware update.
# EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. WRITES THE CAMERA'S FLASH: a battery change does not undo it.
cd "$(dirname "$0")" || exit 1
echo "THIS CHANGES THE CAMERA'S FLASH. A battery change does not undo it; loader_uninstall does."
read -r -p "Type FLASH to go on: " OK
[ "$OK" = FLASH ] || { echo "Nothing was sent."; read -r -p "Press Return to close. "; exit 1; }
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01: " FWV
exec "$PWD/run.sh" batch loader_uninstall --go --writes-flash --firmware-shown "$FWV" "$@"
