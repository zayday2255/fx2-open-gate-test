@echo off
rem FX2 (firmware 1.01): START-UP LOADER, STEP 3. WRITES FLASH: installs the loader with the plan og2560 (the 3840x2560 open gate, 23.98p / 24p) at every power-on on STILL. Only after steps 1 and 2 worked. Undo: loader_uninstall.
rem EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. WRITES THE CAMERA'S FLASH: a battery change does not undo it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
echo THIS CHANGES THE CAMERA'S FLASH. A battery change does not undo it; loader_uninstall does.
set /p OK=Type FLASH to go on:
if not "%OK%"=="FLASH" (
  echo Nothing was sent.
  pause
  exit /b 1
)
set /p FWV=Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01:
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx2_batch.py" loader_install_og2560 --go --writes-flash --firmware-shown %FWV% %*
echo.
echo The results are in windows\camera_private (newest folder).
pause
