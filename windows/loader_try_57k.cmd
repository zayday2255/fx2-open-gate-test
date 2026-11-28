@echo off
rem FX2 (firmware 1.01): START-UP LOADER, STEP 2 with the 5.7K plan. RAM only: brings the loader's files to the RAM disk and runs its helper once with the plan og57 (5760x3840, 300 Mbps on the 100M and higher settings, 23.98p / 24p: L13 K5 K16 X22 S16). From a fresh power-on on STILL. Then loader_status, then MOVIE. A battery change undoes it.
rem EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
set /p FWV=Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01:
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx2_batch.py" loader_try_og57 --go --firmware-shown %FWV% %*
echo.
echo The results are in windows\camera_private (newest folder).
pause
