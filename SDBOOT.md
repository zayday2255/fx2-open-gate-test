# FX2 start-up loader ("sdboot"): open gate at power-on, without a computer

**Experimental. Built and tested in emulation only (2026-11-28). It has not run on a camera.** Firmware 1.01 only.
This page replaces the notes of the `sdboot-research` branch (`sdboot_research/`), whose hook it rebuilds.

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
| `libJit_fx2_X21` | The kit's read-only check built for a process outside the camera application: the same sites, guards and verdict, read from the camera application's maps and memory (issue #16; `check` runs this). |

Plans: `og2560` (3840x2560, 23.98p / 24p), `og2560pal` (25p), `squeeze`, and `check` (reads only).

**The camera must be switched on on STILL.** Wait about 20 seconds, then set MOVIE. Switched on on MOVIE, the first step refuses
(the kit's own rule) and the camera stays stock.

## Issue #16: the check said NOT READY from outside (fixed)

The first tester ran step 1 on a real PAL FX2 (issue #16) and got `check: read; VERDICT NOT READY` while `X18` read the same camera
as READY in the same second. That was a fault of the loader, not of the camera:

- the kit's read-only check looks for `libmpr.so` in **its own** `/proc/self/maps` and reads the encoder-side sites where that
  library is mapped **in its own process**. Inside the camera application that is right. Run as the loader's helper it is the wrong
  process: `busybox true` has no `libmpr.so`, so all six main-processor sites read `NOT MAPPED`, the count of places not as the
  1.01 update goes up, and the verdict is NOT READY on a completely stock camera.
- `X18` said READY because it had already been built for exactly this case: it finds the one process named `im.elf` and reads that
  process's maps and memory.

**The fix (`libJit_fx2_X21`, and the `check` plan now runs it instead of `check X18`):** the kit's check is built once more from its
own source, with the same four changes the encoder levels already had - the map list is the camera application's, and the library
bytes are read through its memory file. Sites, guards, the identity lines and the verdict rule are unchanged, so a stock camera
gives `VERDICT READY` and an applied one gives `TARGET`, exactly as the check does from inside.

Not yet run on a camera: this build is new. `X21` replaces `check` in the `check` plan; `X18` stays in the build but no plan uses it.

## Ran on a camera: the fix works (2026-11-27, ILME-FX2 1.01, NTSC)

Step 1 (`loader_try_readonly`) on the tester's own FX2, from a cold boot on STILL, after the battery was pulled to clear an
earlier 5.7K encoder patch:

- the kit's own check in the same connection said `VERDICT READY`, `encoder side: stock`, `101 stock, 0 target, 0 other`;
- all 17 steps passed in one connection, and `libJit_fx2_X21.so` landed on the RAM disk whole (65,072 bytes, read back and compared);
- the helper started as its own process (`status 0`, camera application **process 543**), and `loader_status` read back its log:

```
fx2boot[usb]: START build fx2boot_v1, files in /tmp_wbshd/fx2boot
fx2boot[usb]: plan check: X21
fx2boot[usb]: camera application: process 543
fx2boot[usb]: the kit's result file is set aside for this run
fx2boot[usb]: X21: read; VERDICT READY (every identity check same, every site stock, target or a test design)
    file /libmpr.so path /usr/lib/libmpr.so mapped 0x7f5cd0e000
fx2boot[usb]: END: plan check, every step done
```

**`VERDICT READY` from outside the camera application** is issue #16 answered: the same step reported `NOT READY` before the fix.
The `file /libmpr.so ... mapped 0x7f5cd0e000` line is the check reaching the camera application's own copy of the library, which is
exactly what the old build could not do.

Still not run on a camera: steps 2 and 3 (the apply at a power-on, and the install on flash).

## Try it, in this order

Every command is a plan of `fx2_batch.py` (one USB connection). The launchers in `windows/` and `macos/` are named after them.
Camera on STILL, fresh power-on, USB (Mass Storage) in. Each step stands on the one before.

| # | Launcher | Writes | What to expect |
|---|---|---|---|
| 1 | `loader_try_readonly` | RAM only, and reads only | Then `loader_status`: `X21: read; VERDICT READY`. This shows the helper can reach the coprocessor and the application from outside. |
| 2 | `loader_try_open_gate` | RAM only; camera memory as the kit's apply does | Then `loader_status`: five steps DONE. Unplug, set MOVIE, record: 3840x2560. A battery change undoes all of it. |
| 3 | `loader_install_open_gate` | **FLASH** | Battery out 10 s. Switch on on STILL, wait 20 s, `loader_status`: the log shows `fx2boot[1]` and five steps DONE. |
| 4 | (switch off and on, battery in) | | `loader_status`: `fx2boot[2]`, four steps DONE and `X19: NOTHING TO DO`. |
| 5 | `loader_uninstall` | **FLASH** (removes) | `loader_status`: nothing installed. |

If step 1 does not give those two lines, stop there and send the session folders: nothing was written.

## Undo

- `loader_uninstall`: removes `/etc/ld.so.preload` first, then the loader's folder, then what the research branch left
  (`/etc/fx2_*`, `/etc/fx2in_*`, `/setting/mode/preload`). It needs none of the loader's files to be intact.
- `loader_off` / `loader_on`: the hook stays but starts nothing.
- A battery change does **not** remove an installed loader. It removes everything steps 1 and 2 did.
- Uninstall before a firmware update.

## What can go wrong, plainly

- Not tested on a camera: whether the camera's message library answers a process outside the application; the timing after
  power-on; the FAT partition's behaviour; whether a camera with Bluetooth and Wi-Fi off starts any program at power-on (if not,
  the hook never runs). Steps 1 and 2 exist to find these out without writing flash.
- The hook file is read by the camera's loader before any check of ours. If that one file were damaged on flash, the programs the
  camera starts would be killed at start until `loader_uninstall` is run. The install never writes it in place: it writes a second
  name, reads it back, checks its SHA-256 and renames it, and writes `ld.so.preload` last.
- Do not start a kit session in the first half minute after power-on while the loader is installed: the helper and the kit use
  the same result file.
- Not done: the SD card as the on/off switch (the card is not visible outside the camera application), a camera switched on on
  MOVIE, 5.7K.

The full notes, with the evidence for each statement, are `a7iv_map\modding\FX2_SDBOOT.md` in the author's map; the sources and
the emulation are in `windows/tools/camera_tests/CT6_memory_read_check/helper_fx2/sdboot/`.
