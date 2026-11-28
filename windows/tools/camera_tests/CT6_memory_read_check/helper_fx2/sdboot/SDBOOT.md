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

Plans: `og2560` (3840x2560, 23.98p / 24p), `og2560pal` (25p), `og57` (5.7K 5760x3840 at 300 Mbps, 23.98p / 24p),
`og57pal` (5.7K on a PAL camera, 25p), `squeeze`, and `check` (reads only).

| Plan | Steps | What it records |
|---|---|---|
| `og2560` | `L13 H5 L16 X19 S16` | 3840x2560, XAVC HS / S 4K, 23.98p |
| `og2560pal` | `L13 P5 L16 X19 S16` | the same, XAVC S 4K 25p |
| `og57` | `L13 K5 K16 X22 S16` | **5760x3840**, 300 Mbps on the 100M and higher settings, 23.98p |
| `og57pal` | `L13 J5 K16 X22 S16` | the same on a PAL camera, 25p |
| `squeeze` | `X20 L13 L5 S16` | 3840x2160 holding the whole 3:2 area, squeezed 27/32 |
| `check` | `X21` | nothing: reads only |

`X19` applies the 4K encoder design (`ogfile2560_hs_s_fx2_v2`); `X22` applies the 5.7K one (`ogfile57r300m1_fx2_v4`, 382 sites against
151). They are separate files, so a plan can never run the wrong encoder table. If a plan cannot finish, `X20` (4K) or `X23` (5.7K) puts
the encoder side back, matching the plan's own encoder step.

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

## Step 2 ran on a camera: both open-gate modes (2026-11-27/28, ILME-FX2 1.01, NTSC)

`loader_try_open_gate` (plan `og2560`) and `loader_try_57k` (plan `og57`), each from a cold boot on STILL, then MOVIE:

| Plan | File | Result |
|---|---|---|
| `og2560` | `Isaiah20261127_0468.MP4` | **3840 × 2560**, HEVC 4:2:2 10-bit, 23.976p, 34.03 s, 816 frames, 110 Mbps |
| `og57` | `Isaiah20261127_0469.MP4` | **5760 × 3840**, HEVC 4:2:2 10-bit, 23.976p, 20.02 s, 480 frames, **300.2 Mbps** |

Both: sample aspect 1:1 and display aspect 3:2 (so the extra rows are real, not a squeezed 16:9), all frames decoded with **no error**,
4 tracks of 24-bit PCM audio and Sony's per-frame metadata track intact. All five steps reported DONE in the helper's log, and the plans
survived the STILL to MOVIE switch - the step that crashed the image processor in issue #1.

A battery pull (10 s) afterwards returned the camera to stock, as designed: the patch lives in RAM only.

The power switch does **not** do this - it leaves the encoder step applied while the rest goes stock (issue #5). Use the battery pull.

## The install, and the bug it found (2026-11-28, ILME-FX2 1.01)

Step 3 (`loader_install_57k`, plan `og57`) ran on the tester's FX2: all 17 files copied to `/etc/fx2boot`, each read back and its
SHA-256 checked, then `/etc/ld.so.preload` written last. `loader_status` afterwards: `the start-up hook is INSTALLED`, `plan: og57`,
`every file is this build's`.

**The hook then refused every boot:**

```
hook: not this build's file, nothing started: fx2boot.sh
```

while the status step said `fx2boot.sh: this build's`. Both were telling the truth: the hook compiles the manifest of every payload
file into itself, and the installed hook was a **stale build** whose manifest held the *old* `fx2boot.sh` (7,306 bytes) and had no
entry at all for `X21` or `X22`. Cause: the local rebuild script reused the existing `fx2hook.so` instead of recompiling it, so after
`fx2boot.sh` grew (the SD switch) and `X22` was added (5.7K), the hook still checked against the old list.

The fix is in the build, and there is now a guard: `pins_for_runner.py --check` reads the manifest compiled into `fx2hook.so` and
fails, naming each file, unless every payload file is there at the right size and SHA-256. Given the stale hook that shipped, it
reports all six missing files and exits non-zero.

**Reinstalled with the rebuilt hook (7,856 bytes, all 16 entries correct) and it works.** All 17 files copied, each read back and
SHA-256 checked, `DONE: the start-up loader is INSTALLED with plan og57`.

Then the loader applied 5.7K **by itself at a power-on**, with no computer attached: the camera came up in open gate. That is the goal
this loader exists for, on hardware.

The one thing that went wrong on the way was the **kill switch doing its job**: an earlier attempt looked like "5.7K was not
enabled", but the card was out at that power-on, so the helper stopped before reading the plan. Correct behaviour, and worth knowing
as a habit: **power on with the card in, wait ~20 seconds for the helper, then set MOVIE.** The patch is applied at power-on, not when
the switch is flipped to MOVIE; inserting the card afterwards does nothing until the next power-on.

## A battery pull did not apply the patch (found 2026-11-28, fixed)

The tester found the behaviour that mattered most, and it was a design fault:

| Power-on | Result |
|---|---|
| battery out and in (cold boot) | **nothing applied** |
| power switch off and on (warm boot) | 5.7K applied |

The hook decided whether to start the helper by reading `/sys/kernel/debug/suspend_stats`, which counts **completed suspends**, and
returned early when it read `0`. But that file is **absent inside the camera application's namespace** (measured: `/proc/uptime` reads
`40.93`, `suspend_stats` reads `absent`), so the count was `0` there regardless of how the camera was turned on. Which boot applied the
patch was therefore close to chance, and a battery pull - the reset this project recommends - reliably did nothing.

The hook now counts a power-on by the boot's own start time: `/proc/uptime` (seconds since boot, the same in every mount namespace)
subtracted from `CLOCK_MONOTONIC`. That value is constant for a whole boot and different after a power cycle, so one helper starts per
power-on and the next boot starts its own. The old suspend count is kept only for the status report.

Two further faults were found and fixed while testing this, both of which could have produced the same symptom:

- The mark file used to be named by a time bucket, which two consecutive boots could share, so the second boot's helper could be
  refused by its own mark. The mark now records the boot's start time and is compared by value.
- The build compiled `fx2hook.so` **before** writing `fx2boot_manifest.h`, so the hook embedded the previous file sizes. That is the
  same class of fault as the stale hook that refused every boot on 2026-11-28, and it is now impossible to miss:
  `pins_for_runner.py --check` reads the manifest compiled into the hook and fails, naming each file, if it does not match.
- **The uptime was read in whole seconds, and the hook runs in the boot's first second.** `/proc/uptime` then reads `0.87`, which
  truncated to `0`, which the code treated as "unreadable" - so the hook still did nothing after a battery pull. It is read in
  milliseconds now (`0.87` -> `870`). This is why the first fix changed nothing on the camera: the log said
  `(none: the helper has not run since the battery was last out)`, i.e. the helper never started at all.

`loader_status` now prints `/proc/uptime` and the mark (the boot's start time) so a decision like this can be read from one run
instead of inferred.

## Try it, in this order

Every command is a plan of `fx2_batch.py` (one USB connection). The launchers in `windows/` and `macos/` are named after them.
Camera on STILL, fresh power-on, USB (Mass Storage) in. Each step stands on the one before.

| # | Launcher | Writes | What to expect |
|---|---|---|---|
| 1 | `loader_try_readonly` | RAM only, and reads only | Then `loader_status`: `X21: read; VERDICT READY`. This shows the helper can reach the coprocessor and the application from outside. |
| 2 | `loader_try_open_gate` | RAM only; camera memory as the kit's apply does | Then `loader_status`: five steps DONE. Unplug, set MOVIE, record: 3840x2560. A battery change undoes all of it. **Ran on a camera 2026-11-27: 3840x2560, 34 s, 816 frames, 4:2:2 10-bit, clean decode.** |
| 2 (5.7K) | `loader_try_57k` | RAM only; the same, with the plan `og57` | `loader_status`: `L13 K5 K16 X22 S16` each DONE. Unplug, set MOVIE, record: **5760x3840** at 300 Mbps. Needs a V90 card or CFexpress Type A. A battery change undoes it. |
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
- Not done: a camera switched on on MOVIE.
- **The SD card as the on/off switch: the signal is found (2026-11-27, on an FX2).** The old note said the card "is not visible
  outside the camera application". It is not visible as a *mount* - `/proc/mounts` in the camera application's own process never
  lists it, with a card in and the camera writing 5.7K clips to it - but it is visible as a **block device**, and cleanly:

  | | card in | card out |
  |---|---|---|
  | `/sys/block` | `mmcb` | absent |
  | `/sys/class/block` | `mmcb`, `mmcb1` | absent |
  | `/dev` | `mmcb`, `mmcb1` | absent |

  Nothing else in those lists changes between the two runs (`nflasha*`, `cnflasha*`, `ram*`, `loop*` are identical), so a card is
  present exactly when `/dev/mmcb1` (a formatted card: whole device plus first partition) or `/dev/mmcb` (any card) exists.
  **`/dev/mmcb-char` stays either way** - it is the slot's controller, not the card - so a switch must test `mmcb`/`mmcb1` and
  not the `-char` node. The usual names do not apply on this camera: `/sys/block/mmcblk0`, `/sys/bus/mmc/*` and
  `/sys/class/mmc_host/*` are all absent, and `mmca` is the internal eMMC (`mmca-char` only).
  **The switch is written (fx2boot.sh):** a power-on with no card stops before the plan is even read - nothing is applied. `run now`
  over USB is deliberately not gated, because that is an operator asking with the camera in their hands. `loader_status` now prints
  the state the helper would see (`ON`/`OFF`) before the raw block-device lines.

  Tested offline in isolation (the gate's own text against a fake /dev): card out stops, `mmcb1` present proceeds, `mmcb` alone
  proceeds with its own line, and `run now` with no card proceeds. Still not run on a camera.

The full notes, with the evidence for each statement, are `a7iv_map\modding\FX2_SDBOOT.md` in the author's map; the sources and
the emulation are in `windows/tools/camera_tests/CT6_memory_read_check/helper_fx2/sdboot/`.
