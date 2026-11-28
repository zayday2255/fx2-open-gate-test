# FX2 start-up loader ("sdboot"): open gate at power-on, without a computer

**Experimental. Tested in emulation. On a camera only step 1 (read-only) has run, once, with the first build.** Firmware 1.01 only.
This is build `fx2boot_v2` (2026-11-28). This page replaces the notes of the `sdboot-research` branch (`sdboot_research/`), whose hook
it rebuilds.

## The first run on a camera (issue 16), and what build v2 changes

A PAL-set FX2 ran step 1 of build v1 (`loader_try_readonly`, then `loader_status`). What it showed:

- The helper starts beside the camera application and finishes its plan. The application is process 543 on that camera too.
- **X18 read the encoder side from outside: READY.** So a process beside the application can read the application's list of mappings
  and its memory.
- **The check said NOT READY. That verdict was certain from outside and says nothing about the camera.** Build v1 ran the kit's own
  check there. It looks for three library files and six `libmpr.so` sites in its own process; beside the application it finds none of
  the nine and counts each as "not as the 1.01 update". The page told you to expect `check: read` and did not say the verdict would
  be NOT READY: that was the page's fault, and the status did not show whether the coprocessor had been read either.

Build v2:

- **X0** takes the check's place in the plan `check`. It is the kit's check built for a process outside the application (as X18 is the
  kit's level 18): the same tables and the same report lines, read from the application's list of mappings and through its memory
  file. In emulation it reports, from outside, line for line what the kit's check reports inside the application, NTSC and PAL.
- The helper's log now says what the check read: the buffer the camera's memory manager gave, and counts for code pages, coprocessor
  sites, files, `libmpr.so` and `av-cam.bin`. `loader_status` shows that log.
- **`loader_report`** (new, read-only) saves the whole result of every step of the helper's last run in the session folder.

Still not known from a camera: whether the coprocessor can be read through `fx2cp.so` (the first line of X0's report answers it), and
everything about steps 2 to 5.

## Where the first attempt was stuck (short report)

- The hook of the research branch (`/etc/ld.so.preload`) works: on a real FX2 it was loaded into the small programs the camera
  starts after power-on (the Bluetooth start script and its tools, among others). It was never loaded into the camera application
  `im.elf`, and the branch stopped there, suspecting that the application is isolated.
- **It is not isolated. It is never started.** The firmware ships a memory image of an already running system, and the camera puts
  that image back at power-on. `im.elf` on the FX2s seen so far is the process that is frozen in that image: same process number
  (543), same randomised addresses, in the shipped image and in three kit sessions from at least two cameras. A preload is read
  only when a program starts, so it cannot reach a program that is restored.
- The other ways to hand `im.elf` a file at start-up (library cache, search path, Sony's debug preload, Sony's stand-alone test
  mode) are closed for the same reason. They were checked one by one in the firmware.
- So at power-on nothing can be loaded into the camera application. What can be started is a helper process beside it. The
  open-gate steps therefore have to be done from outside the application. That is what this loader does.
- One claim of the old runbook is wrong and matters: a damaged hook file is **not** ignored by the camera. A file that is cut
  short kills every program the camera starts. The old installer wrote the file in place and always reported DONE.

## What the loader is

| Piece | What it does |
|---|---|
| `fx2hook.so` | Named in `/etc/ld.so.preload`. Runs in every program the camera starts. In all but one per power-on it makes four system calls and returns. That one starts the helper, after checking every loader file against the SHA-256 list built into the hook. At a cold boot it does nothing. |
| `fx2boot.sh` | The helper, run by the camera's own shell as a process of its own. It runs the kit's step libraries in the kit's order, reads each result as the kit does, and stops at the first that is not DONE. If the plan cannot be finished it puts the encoder side back to stock. It writes RAM only. |
| `fx2cp.so` | Gives the step libraries the three coprocessor-transfer functions they take from the camera's `libsencore.so`, in a process outside the camera application. It makes the same calls with the same bytes as Sony's library (compared call by call in an emulator). |
| `libJit_fx2_L13 / H5 / P5 / L5 / L16 / S16` | The kit's own pinned libraries, unchanged. |
| `libJit_fx2_X18 / X19 / X20` | The kit's encoder step (read / apply / put back) built for a process outside the camera application. |
| `libJit_fx2_X0` | The kit's read-only check built the same way: coprocessor sites through `fx2cp.so`, the application's files and `libmpr.so` through `/proc`. |

Plans: `og2560` (3840x2560, 23.98p / 24p), `og2560pal` (25p), `squeeze`, and `check` (reads only).

**The camera must be switched on on STILL.** Wait about 20 seconds, then set MOVIE. Switched on on MOVIE, the first step refuses
(the kit's own rule) and the camera stays stock.

## Try it, in this order

Every command is a plan of `fx2_batch.py` (one USB connection). The launchers in `windows/` and `macos/` are named after them.
Camera on STILL, fresh power-on, USB (Mass Storage) in. Each step stands on the one before.

| # | Launcher | Writes | What to expect |
|---|---|---|---|
| 1 | `loader_try_readonly` | RAM only, and reads only | Then `loader_status`: the log lines below. This shows the helper can reach the coprocessor and the application from outside. Then `loader_report`, which keeps the whole results in the session folder. |
| 2 | `loader_try_open_gate` | RAM only; camera memory as the kit's apply does | Then `loader_status`: five steps DONE. Unplug, set MOVIE, record: 3840x2560. A battery change undoes all of it. |
| 3 | `loader_install_open_gate` | **FLASH** | Battery out 10 s. Switch on on STILL, wait 20 s, `loader_status`: the log shows `fx2boot[1]` and five steps DONE. |
| 4 | (switch off and on, battery in) | | `loader_status`: `fx2boot[2]`, four steps DONE and `X19: NOTHING TO DO`. |
| 5 | `loader_uninstall` | **FLASH** (removes) | `loader_status`: nothing installed. |

At any point, `loader_report` (read-only) saves the helper's log and the whole result of each of its steps in the session folder.

Step 1 is good when the log in `loader_status` holds these lines (the numbers are a stock camera's; the buffer address is the camera's own):

```
fx2boot[usb]: X0: read; VERDICT READY (every identity check same, every site stock, target or a test design)
fx2boot[usb]: X0: coprocessor buffer (memory manager, through fx2cp.so): buffer physical 0x04........ handle ...
fx2boot[usb]: X0: coprocessor code pages: 4 same, 0 differ
fx2boot[usb]: X0: coprocessor sites: 51 stock, 0 target, 0 test, 0 other, 0 not read, 1 filled at run time (not counted)
fx2boot[usb]: X0: application files: 3 same, 0 differ, 0 not mapped
fx2boot[usb]: X0: libmpr.so sites: 6 stock, 0 target, 0 other, 0 not read
fx2boot[usb]: X0: av-cam.bin: guards 3 same, 0 differ; sites 101 stock, 0 target, 0 other
fx2boot[usb]: X0: places not as the 1.01 update or not read: 0
fx2boot[usb]: X18: read; == level 18 verdict: READY: every guard is as in the file and every site holds the stock bytes
fx2boot[usb]: END: plan check, every step done
```

- `coprocessor buffer ...: !! buffer allocation failed`, or a line starting `fx2cp:`, means the camera's message library did not serve
  a process outside the application. Steps 2 to 5 cannot work then: stop and send the folders.
- `target` in place of `stock` is fine: that part of the open gate is applied on your camera (the encoder side stays through a
  switch-off with the battery in).
- Anything else that is not as above: stop, run `loader_report`, and send the session folders. Step 1 writes nothing to the camera's
  memory or flash.

## Undo

- `loader_uninstall`: removes `/etc/ld.so.preload` first, then the loader's folder, then what the research branch left
  (`/etc/fx2_*`, `/etc/fx2in_*`, `/setting/mode/preload`). It needs none of the loader's files to be intact.
- `loader_off` / `loader_on`: the hook stays but starts nothing.
- A battery change does **not** remove an installed loader. It removes everything steps 1 and 2 did.
- Uninstall before a firmware update.

## What can go wrong, plainly

- Seen on one camera (step 1, build v1): the helper runs beside the application, and reads its mappings and memory.
- Not tested on a camera: whether the camera's message library answers a process outside the application (step 1 of build v2
  says); whether another process may write the application's memory (step 2); the timing after power-on; the FAT partition's
  behaviour; whether a camera with Bluetooth and Wi-Fi off starts any program at power-on (if not, the hook never runs). Steps 1
  and 2 exist to find these out without writing flash.
- The hook file is read by the camera's loader before any check of ours. If that one file were damaged on flash, the programs the
  camera starts would be killed at start until `loader_uninstall` is run. The install never writes it in place: it writes a second
  name, reads it back, checks its SHA-256 and renames it, and writes `ld.so.preload` last.
- Do not start a kit session in the first half minute after power-on while the loader is installed: the helper and the kit use
  the same result file.
- Not done: the SD card as the on/off switch (the card is not visible outside the camera application), a camera switched on on
  MOVIE, 5.7K.

The full notes, with the evidence for each statement, are `a7iv_map\modding\FX2_SDBOOT.md` in the author's map; the sources and
the emulation are in `windows/tools/camera_tests/CT6_memory_read_check/helper_fx2/sdboot/`.
