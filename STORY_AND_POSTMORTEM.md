# The whole story: 24 hours from working open gate to a boot-looping camera

Written 2026-11-28 04:13 PST, for A and anyone else who wants to re-derive this rather than take my word for it.
Camera: **Sony ILME-FX2, firmware 1.01**. Everything below happened on one physical camera.

**Read this if you want to help.** Sections 7–9 are the part that matters: what state the camera is in, what has been ruled out
with evidence, and the open questions. Sections 1–6 are how it got here, so you can check whether my reasoning was sound at each
step — because it wasn't, at the step that mattered.

---

## 1. Starting point: open gate already worked (inherited)

The kit (`fx2-open-gate-test`, firmware 1.01 port of the A7 IV open gate) already worked over USB: apply a few RAM patches from
a cold boot on STILL, flip to MOVIE, record 3840×2560 or 5760×3840. RAM only; a battery pull reverts.

Existing open issues: **#16** (the read-only check says NOT READY when run from outside the camera app) and **#5**
(the power switch leaves the encoder half-applied).

## 2. Fixing #16 (this worked)

**Symptom.** Step 1 reported `VERDICT NOT READY` on a stock camera while `X18` read the same camera as READY at the same moment.

**Cause.** The kit's check looks for `libmpr.so` in **its own** `/proc/self/maps`. That is correct inside `im.elf`. Run as the
loader's helper it is the wrong process, so all six `libmpr` sites read `NOT MAPPED`.

**Fix.** `libJit_fx2_X21` — the same check generated from its own source with the same four edits the encoder levels already used
(the map list comes from the camera application, bytes read through its memory file). Sites, guards and the verdict rule unchanged.

**Verified on the camera:** `X21: read; VERDICT READY`, and `file /libmpr.so … mapped 0x7f5cd0e000` — the check reaching `im.elf`'s
own copy of the library from outside, which the old build could not do. Commit `45ca2fc`, hardware result `9292d6c`.

## 3. Adding 5.7K plans (this worked)

`og57` = `L13 K5 K16 X22 S16`. `K5`/`J5`/`K16` are the kit's pinned libraries; **`X22` had to be built** because the existing `X19`
is compiled against the *4K* encoder design (`ogfile2560_hs_s_fx2_v2`, 151 sites) and cannot apply the 5.7K one
(`ogfile57r300m1_fx2_v4`, 382 sites). `X22`/`X23` are levels 19/20 built against the 5.7K header.

Also fixed: the helper's failure path always undid the encoder with `X20` (the 4K design), which on a 5.7K run would have put back
the wrong table.

**Verified on the camera:** `og57` recorded **5760×3840, HEVC 4:2:2 10-bit, 23.976p, 300.2 Mbps, 480 frames, every frame decodes.**
`og2560` recorded **3840×2560**, same properties. Commits `edae964`, `a5acf3a`.

## 4. The SD card as a kill switch (this worked)

Probed read-only. Key finding, contradicting the old research note: the card is **not** a mount (it never appears in
`/proc/mounts`, even while the camera writes 5.7K to it) but it **is** a block device:

| | card in | card out |
|---|---|---|
| `/sys/block` | `mmcb` | absent |
| `/sys/class/block` | `mmcb`, `mmcb1` | absent |
| `/dev` | `mmcb`, `mmcb1` | absent |

Everything else identical. **`/dev/mmcb-char` stays either way** — it's the slot controller, not the card, so a switch must not test
it. `fx2boot.sh` now stops before reading the plan if no card. Verified both states on the camera (`ON` / `OFF`). Commits
`4761833`, `590a030`.

## 5. Installing on flash, and the stale-hook bug (this broke, then worked)

First install succeeded (17 files copied, each read back and SHA-256 checked) but **every boot was refused**:
`hook: not this build's file, nothing started: fx2boot.sh`.

**Cause:** the hook compiles a manifest of every payload file into itself, and my local rebuild script **reused the existing
`fx2hook.so` instead of recompiling it** — so it carried the previous `fx2boot.sh` size (7,306 vs 9,306) and had no entry for `X21`
or `X22`. Guard added: `pins_for_runner.py --check` now reads the manifest compiled into the hook and fails, naming each file.
Commit `d38e64f`.

Reinstalled with the rebuilt hook. **Then 5.7K applied by itself at a power-on with no computer attached** — the actual goal.
Commit `b0df93e`.

## 6. THE BUG. One line, and it bricked the camera

`fx2hook.c`, as installed (commit `67eb240`):

```c
static u64 boot_start(void)
{
    u64 up = uptime_ms();
    ...
    u64 now = (u64)ts[0] * 1000UL + (u64)ts[1] / 1000000UL;   /* CLOCK_MONOTONIC, ms */
    return now - up;                     /* <-- UNDERFLOWS */
}
```

`CLOCK_MONOTONIC` on this camera **does not count from boot**. When `now < up` the subtraction wraps to ~1.8×10¹⁹. The mark written
to `/tmp_wbshd/fx2boot.mark` therefore differs on every call, `claim_boot()`'s `mark_value() == start` comparison **never matches**,
and **every program the camera starts** believes it is a fresh boot and forks a helper.

**Why it is fatal rather than bad:** the helper's last act is
`execve("/bin/busybox", {"busybox","sh","/etc/fx2boot/fx2boot.sh",…})`, and **busybox is dynamically linked**, so it reads
`/etc/ld.so.preload`, runs the hook, and forks again. The chain is **self-sustaining from a single program**. That is why turning
Bluetooth and Wi-Fi off changed nothing — measured, 56 helpers either way (`macos/sim_bootloop.py`).

Kernel config makes this a reset, not a hang: `wdt.timeout=500 wdt.mode=1 exception.reboot=1 exception.stop=1`.

### The sequence of my own wrong attempts, so you can skip them

| Attempt | What I believed | What was actually true |
|---|---|---|
| Count power-ons by `/sys/kernel/debug/suspend_stats` | non-zero each boot | **absent** in the camera app's namespace → always 0 → hook did nothing |
| Read uptime in whole seconds | a boot's uptime is ≥1 s | the hook runs in the **first second**; `0.87` truncated to `0` → treated as unreadable → did nothing |
| Read uptime in **milliseconds** | now it works | worked, but the **mark comparison** was still value-equality on a per-program value → fork storm |
| `CLOCK_MONOTONIC − uptime` as a boot id | the monotonic clock starts at boot | **it doesn't.** Underflow. This is the one that reached flash. |

None of these was tested against the project's own 78-check emulator (`emu/emu_fx2boot.py`), which tests power-on counting and
would have caught the last one immediately. It needs the firmware tree and WSL, which were not on this machine — **and I skipped it
rather than fixing that.**

## 7. What the camera does now (measured, not described)

| Time (PST) | Observation |
|---|---|
| ~23:10 | After installing `67eb240`: camera restarts every ~20 s, menus partly respond, MOVIE freezes it |
| 00:45–01:41 | USB: `054c:0000` (idProduct **0** — died mid-enumeration) for ~1 s, roughly once per 1–3 min |
| 02:16–03:00 | USB: `054c:0d68`, interface **class 3 only**, present 3 s / absent ~31 s, period ~34 s |
| — | One appearance lasted **79 s**; one `096f` lasted 16 s. Pattern is **bursty**, not a fixed loop |
| 03:30 onward | Screen goes black **with no backlight** (panel powered down, not merely unstarved) |
| 04:09 onward | **Nothing on USB at all**, across two cables |

Measured durations from `macos/service_watch.log`: present `[79, 3, 3, 3, 3, 3, 3, 2, 3, 3, 3]`, period
`[79, 32, 45, 37, 27, 35, 36, 35, 32, 33, 37]`.

## 8. What is on the camera's flash, and what must be undone

```
/etc/ld.so.preload          one line: /etc/fx2boot/fx2hook.so      <-- THIS is the problem
/etc/fx2boot/               17 files (fx2hook.so 26a62ed5…, fx2boot.sh,
                            fx2cp.so, libJit_fx2_{X18,X19,X20,X21,X22},
                            L13/H5/P5/L5/L16/S16/K5/J5/K16, plan=og57)
```

Both on **`nflasha10`**, mounted `rw` vfat, also at `/tmp` and `/var`. Survives a battery pull.

**Removing `/etc/ld.so.preload` is sufficient.** Everything else is inert without it. `W41` (the uninstall) does exactly this,
and deletes the preload **first** so it needs none of the loader's files to be intact.

`nflasha7` (rootfs) and `nflasha15` (`/usr`) were never written — both mounted **ro** the whole time. This is a userspace-hook
soft-brick, not a flash brick.

## 9. Ruled out, with the evidence — please don't re-do these

| Route | Evidence it fails |
|---|---|
| Mass storage (`054c:0f47`) uninstall | Never reached since the storm began. Only `0d68`/class 3, and now nothing. |
| Service mode (`054c:0336`) | Never appears. `init2` runs `setup_senser()` before `bootin.elf`, but `sen.elf` also loads `/etc/ld.so.preload` and dies. |
| **PTP injection** (`PTP_OC_SonyReqReconnect = 0x9282`) | **Proved impossible on this body:** `0d68` presents **only class 3**, no class 6, so `MtpContext` cannot open a PTP channel. `macos/ptp_probe.py` prints this. |
| Settings: BT/Wi-Fi off, USB→Mass Storage | Simulated and measured: the chain needs no new programs. The USB-mode setting also **does not persist** (`/setting` is written by `im.elf`, the process dying). |
| Factory reset | Clears `/setting` (`nflasha2`). Hook is on `nflasha10`. Wrong partition. |
| Format / populate SD card | Nothing reads card **contents** at boot. `mmcb1` is only tested for existence. |
| Card auto-update with the local `BODYDATA.DAT` | It **is** 1.01 (`SHA-256 7c12d1e4…`; decrypted: model `0x50040002`, version 1.01, mode `'U'`). Camera is already 1.01 → `STAT_INVALID_VERSION 0x142`. |
| Spoofing a 1.02 header | Version lives in the AES-encrypted `FDAT`; `fwtool`'s `AesCbcCrypter.encrypt()` raises `Encryption not supported`. **A half-written flash is the only unrecoverable outcome — do not attempt.** |
| 15-pin UART (A's idea) | **Not ruled out.** See `FOR_A_UART_RECOVERY.md`. |

## 10. The firmware, opened up (for whoever wants to simulate)

The 1.01 update decrypts. This was previously recorded as "No decrypter found" in `FX2_Report/CODEX_HANDOFF.md`; that note is
**wrong** — crypter **`CXD90057_k8`** works.

```
BODYDATA.DAT  -> UFU container: DATV, PROV, UDID, FDAT, DEND
                 UDID: normal descriptors 054c:0448…0f47 ; updater 054c:03e2
                 FDAT: AES-CBC, crypter CXD90057_k8  -> 887,738,880 bytes
                 FDAT header: 'UDTRFIRM', modeType 'U', luwFlag 'N',
                              version 1.01, model 0x50040002, 2 filesystems
                 FS[0] 'U' at 0x200, 0x133000 bytes  -> SquashFS (the updater)
                 FS[1] 'P'                           -> empty in this image
FDAT payload -> plain TAR:
   0300_partconf/partinf.conf        partition table (start/size/type per nflasha)
   0100_config/mount.conf            every mount point
   0700_part_image/dev/nflasha3      32 MB FAT  -> vmlinux.bin, initrd.img, adam_app.bin, …
   0700_part_image/dev/nflasha5      262 MB      warm boot image
   0700_part_image/dev/nflasha7      5 MB  ext2  rootfs
   0700_part_image/dev/nflasha8      26 MB FAT   cp data
   0700_part_image/dev/nflasha15     527 MB ext2  /usr
   0800_appli/setting/               factory contents of /setting
initrd.img -> ext2, contains /sbin/init, /sbin/init2, /sbin/initrc/*
```

**Two facts that matter most for recovery:**

1. **The 1.01 update writes only `nflasha3/5/7/8/15`.** It does **not** write `nflasha10`, where `/etc` lives. So a 1.01 reflash
   would **not** remove the hook. (It *does* rewrite `nflasha3`, the initrd.)
2. **The initrd's `/etc` is empty**, and its boot chain is:

```sh
# /sbin/init
. $INITRC_DIR/setup_rootfs          # mounts fstab.root, pivot_root to nflasha7
/sbin/init2

# /sbin/init2
MODE_FILE=/setting/mode/dmode ; SEN_FILE=/setting/sen/smode ; DEFAULT_MODE=3
setup_bis()    { [ "$(cat /proc/udm/upm_bootmode)" != "BIS" ] && return 1 ; … }
setup_senser() { [ "$(cat $SEN_FILE)" == "UU" ] && /usr/bin/sen.elf & ; }
MODE=`cat $MODE_FILE`               # plain TEXT FILE on the rw vfat /setting
if [ "$MODE" != "0" ] ; then
    setup_bis || setup_senser
    /usr/bin/bootin.elf &           # ← starts im.elf; the hook breaks this whole subtree
fi
```

Note the initrd's fstab mounts `nflasha10` at **`/tmp` only**; `/etc` is a later mount.

## 11. Open questions — the ones worth your time

1. **Does the bootloader print to a UART before `console=ttynull0` applies?** `nflasha3` has the kernel and initrd but not the
   loader, so its console config is in the BIS/UDM area. If it prints, a serial attach tells us where the boot dies.
2. **Which of the five UARTs (`f1000000`…`f1004000`) is on the 15-pin connector**, and at what level? `cfg.uart=1` is in the cmdline.
   If `console=` could be made `ttyAMA0`, the initrd's `setup_console` would give **`ash --login` on serial** — a root shell with
   `/setting` writable.
3. **Is `/proc/udm/upm_bootmode` settable** from the bootloader or a debugger? Setting it to `BIS` enters update mode without
   needing a newer firmware.
4. **Is `nflasha10` rewritten by a different update mode?** `common.src` defines `MODE_USER=0 MODE_PROD=1 MODE_SERVICE=2
   MODE_MINOR=3 MODE_VERSKIP=6`, and `keep_big_backup.sh` branches on `$USER|$SERVICE|$MINOR|$MSCRYPT`. If some mode reformats
   `nflasha10`, a reflash in *that* mode would fix this. Needs the `libupdaterbody.so` `UPDATER_ACTION_MODE` enum read properly.
5. **Is there a genuine firmware newer than 1.01 for the ILME-FX2?** If so this is over: card flash, `setup_bis`, initrd `/etc`
   empty, hook never read. **Highest-value question on the list.**

## 12. Tools on this branch (`sdboot-loader`)

| File | What it does |
|---|---|
| `macos/sim_bootloop.py` | **The loop model.** Parameters taken from the initrd's own scripts and the kernel cmdline. Reproduces 1.1 s to reset, 56 helpers, and shows BT/Wi-Fi off changing nothing. Start here. |
| `macos/ptp_probe.py` | Read-only PTP probe. Prints every interface class and whether class 6 / `0x9282` is available. |
| `macos/pounce_uninstall.py` | Pre-stages everything, polls libusb at 50 ms, fires `W41` on a **usable** appearance (class 8 or 255). `--armed-only` reports without sending. |
| `macos/fast_uninstall.py` | Uninstall with the measured dead time removed (~5 s → ~2.5 s). |
| `macos/window_watch.sh` | Shouts when an appearance lasts long enough to act on. |
| `macos/service_mode_watch.sh` | Watches for `0336` and uninstalls on sight. |
| `macos/watch_usb.sh` | Timestamped USB log. |
| `HANDOFF_RESTART_LOOP.md` | Compact state-of-play from 02:21. |
| `FOR_A_UART_RECOVERY.md` | The UART/Pico route in detail. |

Re-extraction recipe (a Mac reboot clears `/tmp`):

```bash
brew install squashfs mtools e2fsprogs
# fwtool lives at ~/Documents/Codex/2026-11-25/investigate-why-the-experimental-open-gate/tools/fwtool
python3 - <<'PY'
import sys; sys.path.insert(0,'<fwtool dir>')
from fwtool.sony import dat, fdat
d = dat.readDat(open('<path>/BODYDATA.DAT','rb'))
name, dec = fdat.decryptFdat(d.firmwareData)          # -> CXD90057_k8
open('/tmp/fdat_plain.bin','wb').write(b''.join(iter(lambda: dec.read(1<<20), b'')))
PY
# FDAT payload: dd skip=0x133200 count=886480896, then: tar -xf
# nflasha3 (FAT): mcopy -i ... ::INITRD.IMG  ;  initrd.img (ext2): debugfs -R "rdump / out/"
# FS[0] (SquashFS, the updater): unsquashfs
```

## 13. The honest post-mortem

Steps 2, 3 and 4 were each proven on the emulator and then on the camera before being relied on. **Step 6 was not.** The hook
went to flash after being validated against my own scratch simulation — which encoded my arithmetic rather than the camera's
behaviour — and the project already had a 78-check emulator that tests exactly this. I skipped it because it needed the firmware
tree and WSL, and I did not want to set them up at 11 pm.

The cost of that shortcut is a camera that does not boot. One line of arithmetic, and one test not run.

If you simulate this: **the interesting question is not "why does it loop"** — `sim_bootloop.py` answers that. It is **"how do you
get one program's worth of execution on a camera whose every program is compromised."** That is what the UART question reduces to.
