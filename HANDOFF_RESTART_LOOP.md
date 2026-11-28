# HANDOFF — FX2 boot loader: camera is in a restart loop (2026-11-28 02:20 PST)

Written for Fable 5.2. The user is **still working on it** — this is a working handoff, not a post-mortem.
Read `SDBOOT.md` first for what the loader is; this page is the *current situation* and what to do next.

## One-paragraph situation

A start-up loader was built and **installed on the camera's flash**. It applies 5.7K open gate at every power-on.
It has a bug that makes it start a helper process in **every program the camera launches**, which thrashes the camera into a
**restart loop**. The camera is not bricked — it powers on, menus partly respond, the screen works — but it restarts before
USB can enumerate, so the uninstall cannot be run over USB. **The remaining route is a firmware reflash from BODYDATA.DAT.**

## What is installed on the camera (the thing to remove)

From `windows/camera_private/CT6_20261128T070915Z_fx2_batch_loader_install_og57/manifest.json`:

| Item | Value |
|---|---|
| Hook library on flash | `fx2hook.so`, SHA-256 starts **`26a62ed583d1fac8`** = commit **`67eb240`** |
| `/etc/ld.so.preload` | one line: `/etc/fx2boot/fx2hook.so` |
| `/etc/fx2boot/` | 17 files (hook, `fx2boot.sh`, `fx2cp.so`, step libraries, `plan` = `og57`) |
| Partition | `/etc` = `nflasha10`, **rw vfat** — survives a battery pull |

**Nothing in a menu can remove this.** Sony's "Reset/Initialize" clears `/setting` (`nflasha2`), a different partition.

## The bug (root cause, for whoever fixes the code)

`fx2hook.c`, commit `67eb240`, `boot_start()`:

```c
return now - up;   /* CLOCK_MONOTONIC ms minus /proc/uptime ms */
```

`CLOCK_MONOTONIC` on this camera does **not** count from boot. When `now < up` the subtraction **underflows** to ~1.8e19, so the
computed value differs every call, `mark_value()` never matches, and **every program claims a fresh boot** and spawns a helper.
Dozens of helper processes per second → restart loop.

A fix exists in the **working tree but is uncommitted and half-written** (see "Repo state"). It has NOT been built (the zig venv
was wiped by the macOS reboot) and NOT tested. **Do not flash it without proving it in the emulator first.**

Related, already fixed earlier and worth knowing: `power_on_number()` reads `/sys/kernel/debug/suspend_stats`, which is **absent**
inside the camera application's namespace, and truncating `/proc/uptime` to whole seconds gives 0 in a boot's first second. Both
were earlier attempts at "one helper per boot"; both were wrong. See `SDBOOT.md` for the history.

## Why USB recovery does not work (measured, not assumed)

- `machines/.../CT1_usb_first_contact` lister: **0 mass-storage, 0 service devices**.
- `ioreg`: the camera appears as `054C:0000` — **idProduct 0, i.e. it died mid-enumeration** — for about **1 second**, and only
  about **once every 1–3 minutes**. Empty 60-second windows are common (`macos/usb_watch.log`).
- Earlier, when healthy, it enumerated as `054C:0F47` (mass storage) and `054C:0D68` (PC Remote/HID).
- The uninstall needs ~2 s of a live connection *after* a USB mode switch (~3–5 s total). The window is too short.
- **The original research's assumption does not hold for this hook.** It relied on `sen.elf` (USB service daemon) starting
  *before* the preload, because that hook was `/setting/mode/preload` (read by `bootin.elf` for `im.elf` only). This loader used
  **`/etc/ld.so.preload`, which every program reads from early boot** — including `sen.elf`. So service mode is unreachable too.

## The route that should work: reflash from BODYDATA.DAT

Firmware update runs at **bootloader/UDM level** (`init2 setup_bis()`, triggered by `/proc/udm/upm_bootmode == "BIS"`), and **the
initrd's own `/etc` is empty**, so `ld.so.preload` is never read. Quoting the firmware trace in `FX2_Report/sd_autoboot_design.md`:
"a stock firmware update would overwrite a bricked rootfs. A userspace-hook brick would be recoverable."

### The file

```
/Users/isaiahadeoye/Downloads/BODYDATA.DAT      891221472 bytes, 23:26 Nov 27
SHA-256 7c12d1e46abcb89b111fb87271a93710...     = the EXACT 1.01 image this project came from
```

Confirmed: `PORT_NOTES.md` names `7c12d1e4…` as the FX2 1.01 update. **So this file is 1.01, and the camera is already on 1.01**
— which is why a card-insert auto-prompt did not appear (same version).

A second copy, different build, is at
`/Users/isaiahadeoye/Assets/Software_Firmware/Camera_Firmware_Settings/BODYDATA.DAT` (809 MB, `595991ae…`) — **unidentified
version, do not use without identifying it.**

### The blocker

Sony's version check is **inside the camera** (the file's `UDID`/`PROV` blocks are signed; `QueryVersionResponse` has old *and*
new version fields, and `STAT_INVALID_VERSION = 0x142` exists). **Do not modify or spoof the file** — a signature failure mid-flash
is the one genuinely destructive outcome.

So the reflash needs either:
1. Sony's **updater application** (it can offer a reinstall rather than a version compare), or
2. **any newer firmware** (1.02+) for the ILME-FX2, which would make the check moot, or
3. the card route **if** the camera will enter BIS mode for it (it did not prompt on boot — untested whether
   *Menu → Setup → Version → Software Update* is reachable, since that menu freezes).

## Repo state (branch `sdboot-loader`, pushed to fork `zayday2255/fx2-open-gate-test`)

```
67eb240  read the uptime in milliseconds - the hook runs in the boot's first second   <- INSTALLED ON THE CAMERA
79adc66  a power-on is counted by the boot's start time (has the underflow bug)
b0df93e  installed, and 5.7K applied by itself at power-on (steps 1-3 verified)
d38e64f  rebuild the hook with its manifest, and guard against a stale one
ecf9e20  install launchers for the 5.7K plan
590a030  the SD card as an on/off switch (card out = nothing applied)
```

**Uncommitted in the working tree:**

- `helper_fx2/sdboot/fx2hook.c` — **draft only, DOES NOT COMPILE.** Verified 2026-11-28 02:25:
  `error: unused function 'mark_value' [-Werror,-Wunused-function]` — i.e. the new `claim_boot` no longer calls it, but the
  function and its comment block were left behind, and the comment still contains a self-contradicting mid-edit sentence
  ("...no: the file is deleted, so a later program WOULD create it..."). The intent was: drop `CLOCK_MONOTONIC` entirely, and use
  a `/tmp_wbshd/fx2boot.done` claim token that the hook creates with `O_EXCL` and the helper never removes, so exactly one helper
  starts per boot, cleared only when the RAM disk is cleared. **Finish it, then prove it in `emu/emu_fx2boot.py` before building.**
- `macos/loader_uninstall_retry.command` — **untried**, waits 20 min, retries the one-step uninstall on every appearance.
- `macos/watch_usb.sh` — the watcher that produced the evidence above. Usage: `./watch_usb.sh 120`.

**Toolchain note:** the zig 0.13.0 venv is at `/tmp/zigvenv` (restored 02:24 after the macOS reboot wiped `/tmp`). Rebuild with
`ZIG_CC="/tmp/zigvenv/bin/python -m ziglang cc"` and `build_fx2boot.py`. `/tmp/zigcc.sh` is a helper wrapper. With no firmware
tree on this machine, keep the published `fx2cp.so`. Expect to re-restore after any reboot.

## What was verified working BEFORE the loop (all on this FX2)

| Step | Result |
|---|---|
| 1 read-only check from outside `im.elf` | `X21: read; VERDICT READY` — issue #16 fixed |
| 2 apply at power-on, `og2560` and `og57` | real clips: 3840x2560 and **5760x3840 @ 300 Mbps**, all frames decode |
| SD-card kill switch | card in → `ON`, card out → `OFF` (verified both states) |
| 3 install on flash | files verified on flash; then the loop began |

So the RAM-only path (`loader_try_57k`) is **proven good** and is what the user should use once the camera is recovered.

## What the user reported, in their words

- "it freezes in usb mode and restarts every 20 seconds"
- "even with the card out it's still doing it"
- "even when the switch is off with the battery in it keeps booting"
- "i can click through the menu but as soon as i hit reset version it freezes"
- "When I went in the setting to change the USB mode to always do mass storage, it changed and I exited out of the menu, but it
  didn't save on the boot ups." → the settings write does not survive, consistent with restarting before/while it lands.
  **Worth testing: change the setting, then pull the battery immediately and see if it persists.**

## Immediate next actions, in order

1. **Try the untried retry uninstaller** while the camera is powered with Bluetooth+Wi-Fi off and USB→Mass Storage:
   `./loader_uninstall_retry.command` (type `FLASH`). Leave it 20 minutes.
2. **Test whether a setting survives a battery pull** (change USB mode → battery out immediately → check). If it persists, the next
   boot enumerates as `0f47` and the uninstaller has a real chance.
3. **Get a newer FX2 firmware (1.02+)** or Sony's updater app, and reflash. This is the only route that does not depend on the
   camera app working.
4. **Only then** fix the hook properly: build it, **prove it in `emu/emu_fx2boot.py`** (78 checks; needs the firmware tree + WSL),
   and prove "one helper per boot" in simulation across cold and warm boots **before** any flash write.

## Things NOT to do

- Do not modify `BODYDATA.DAT` (signed; a failed flash is unrecoverable).
- Do not reinstall or update the loader on this camera until the hook is proven in emulation.
- Do not pull the battery during a firmware write. Charge fully first.
- Do not trust `fx2_batch.py`'s exit status for success — read the session's `manifest.json` (the retry script does this).

## The honest lesson

Steps 1 and 2 were proven in the Unicorn emulator and on hardware before touching flash. **Step 3 was not.** The hook was built,
installed, and only then found to mis-count power-ons — three different ways, in sequence. The emulator test
(`emu/emu_fx2boot.py`, 78 checks including power-on counting) existed and was skipped because it needs the firmware tree and WSL,
which were not on this machine. That skip is what put the camera in this state.
