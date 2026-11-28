@echo off
rem FX2 (firmware 1.01): START-UP LOADER, STEP 1. RAM only and READS only: brings the loader's files to the camera's RAM disk and runs its helper once with the plan 'check' (it reads the coprocessor and encoder sites from outside the camera application). Then run loader_status. A battery change removes everything.
rem EXPERIMENTAL, firmware 1.01 only: read SDBOOT.md first. Writes no flash: a battery change (10 seconds) removes everything it did.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
set /p FWV=Firmware version shown in the camera's menu (Setup, Version), e.g. 1.01:
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx2_batch.py" loader_try_check --go --firmware-shown %FWV% %*
echo.
echo The results are in windows\camera_private (newest folder).
pause
