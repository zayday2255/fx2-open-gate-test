# For A — FX2 boot loop, and your Pico/UART idea

Short version: **you're right that UART is the remaining route**, and the firmware supports it better than I first
reported. Below is what's actually installed, what's already ruled out (with evidence, so you don't re-do it), and the specific
things I could not answer that your hardware access could.

Camera: **Sony ILME-FX2, firmware 1.01.** It powers on, menus partly respond, screen goes black with **no backlight** after a
while, and it restarts. It does **not** currently enumerate on USB at all. Nothing here is bricked at the flash-controller level:
`nflasha7` (rootfs) and `nflasha15` (`/usr`) are mounted **ro** and were never written.

---

## 1. What is actually wrong

I installed a start-up loader that applies open gate at power-on. Its hook lives at `/etc/ld.so.preload` pointing at
`/etc/fx2boot/fx2hook.so` (SHA-256 `26a62ed5…`), installed 2026-11-28 07:09Z with plan `og57`.

**The hook has a bug of mine:** it counts power-ons by `CLOCK_MONOTONIC − /proc/uptime`, which **underflows** when the monotonic
clock is smaller than the uptime. Every value then differs, so **every program the camera starts** claims a fresh boot and forks a
helper. The helper's last act is `execve("/bin/busybox", …)`, and busybox is dynamically linked, so **it loads the hook too and
forks again.** The chain is self-sustaining from a single program — this is why turning Bluetooth and Wi-Fi off changed nothing.

It reproduces in `macos/sim_bootloop.py` (~1 s to watchdog trip, matching the camera). Kernel is configured
`wdt.timeout=500 wdt.mode=1 exception.reboot=1 exception.stop=1`, so it resets rather than hangs.

**Removal needs exactly one thing: delete `/etc/ld.so.preload`.** Everything else about the loader is harmless without that line.

---

## 2. Your UART idea — evidence from the extracted firmware

I decrypted the 1.01 update and pulled the boot images apart. Relevant findings:

- **Five PL011 UARTs are mapped and bound**, not three:
  `f1000000`, `f1001000`, `f1002000`, `f1003000`, `f1004000`.
- Kernel command line: **`console=ttynull0`** — console is routed to a **null sink** on purpose. `cfg.uart=1` is also set.
- So **Linux userspace will not talk on a UART.** But the **bootloader and kernel decompressor run before `console=` takes
  effect**, and that is where the Pico would have something to see.
- The initrd **does** have serial console support: `/sbin/initrc/setup_console` looks for `console=` and creates a device node for
  `ttymxc0`, `ttyAMA0` or `ttyO0`. It does **not** handle `ttynull0`, so it falls through to `ash --login` on the inherited tty.
  **If the kernel command line could be made to say `console=ttyAMA0` (or whichever PL011 this SoC's 8250 driver names it), the
  initrd would give you a root shell.** That is the part worth your attention — it depends on where the cmdline lives.

### What I could not determine (needs hardware or the bootloader binary)

1. **Which of the five UARTs is wired to the 15-pin multi connector**, and at what baud/voltage level. Nothing in the firmware
   names the connector's pins. This is the one thing only a scope or a schematic settles.
2. **Whether the bootloader prints before Linux starts.** `nflasha3` contains `vmlinux.bin` and `initrd.img` plus `adam_app.bin`,
   `wole_app.bin`, `bonobo.bin` — the loader itself is not in that partition, so its console config is elsewhere (likely the
   BIS/UDM area). If it prints, you'll see it immediately on a plain serial attach.
3. **Whether the bootloader accepts input.** If it has a shell or a "press a key" prompt, recovery is easy; if it is output-only,
   UART is diagnostics only.
4. **`/proc/udm/upm_bootmode`** — `init2` runs `setup_bis()` only when this reads `"BIS"`. If it is writable from a debugger/serial
   command, that is a clean way to force update mode without a firmware version change.

---

## 3. Already ruled out — do not spend time here

Each of these was tested on the camera tonight, not assumed:

| Route | Why it fails |
|---|---|
| USB mass storage uninstall | Camera never reaches `054c:0f47`. It cycles `054c:0d68` (HID, class 3) for ~3 s every ~35 s, and now not at all. |
| USB **service** mode (`054c:0336`) | Never appears. `sen.elf` starts before `bootin.elf` but loads the hook too, so it dies in the same storm. |
| PTP injection (`PTP_OC_SonyReqReconnect = 0x9282`) | **Proved impossible:** `0d68` presents **only interface class 3**, no class 6, so there is no PTP channel. `MtpContext` cannot open it. |
| Settings (Bluetooth/Wi-Fi off, USB mode → Mass Storage) | Reduced nothing; the chain needs no new programs. The USB-mode setting **does not persist** across a restart (settings live in `/setting`, written by `im.elf`, which is the process dying). |
| Sony factory reset | Clears `/setting` (`nflasha2`). The hook is on **`nflasha10`** (`/etc`). Wrong partition. |
| Formatting the SD card | Same reason — and nothing reads card *contents* at boot. |
| Card auto-update with `BODYDATA.DAT` | The file in `~/Downloads` is **1.01** (`SHA-256 7c12d1e4…`, verified by decrypting it: model `0x50040002`, version 1.01). Camera is already 1.01, so it is refused. |
| Spoofing 1.02 | **Do not attempt.** The version lives in the AES-encrypted `FDAT` header; `fwtool`'s `AesCbcCrypter.encrypt()` raises `Encryption not supported`, so a modified file cannot be re-signed. A half-written flash is the one unrecoverable outcome. |

---

## 4. Tooling that exists here and works

All committed on branch `sdboot-loader` (fork `zayday2255/fx2-open-gate-test`):

| File | What |
|---|---|
| `HANDOFF_RESTART_LOOP.md` | The full technical record of tonight |
| `macos/ptp_probe.py` | Read-only PTP probe; **already showed `0d68` has no class-6 interface** |
| `macos/pounce_uninstall.py` | Pre-stages everything, polls libusb at 50 ms, fires W41 the instant a **usable** mode (class 8 or 255) appears. `--armed-only` just reports |
| `macos/fast_uninstall.py` | The uninstall with the measured wasteful parts removed (~5 s → ~2.5 s) |
| `macos/sim_bootloop.py` | Reproduces the loop from the camera's real boot scripts |
| `macos/service_mode_watch.sh`, `window_watch.sh`, `watch_usb.sh` | Watchers; `window_watch.sh` shouts when an appearance lasts long enough to act |
| `/tmp/fwx/` | **The extracted 1.01 update** — `0300_partconf/partinf.conf` (partition table), `0700_part_image/dev/nflasha3` (initrd FAT: `vmlinux.bin`, `initrd.img`), `0800_appli/setting/` (factory `/setting`) |
| `/tmp/initrd_x/` | The initrd unpacked — `sbin/init`, `sbin/init2`, `sbin/initrc/*` |

To re-extract from scratch if `/tmp` is gone (the Mac reboots clear it):

```
brew install squashfs mtools e2fsprogs
# decrypt: fwtool at ~/Documents/Codex/2026-11-25/.../tools/fwtool, crypter CXD90057_k8
python3 -c "from fwtool.sony import dat, fdat; d=dat.readDat(open('~/Downloads/BODYDATA.DAT','rb')); n,dec=fdat.decryptFdat(d.firmwareData); ..."
# FDAT payload is a plain TAR -> tar -xf ; nflasha3 is FAT -> mcopy -i ... ::INITRD.IMG ; initrd is ext2 -> debugfs -R "rdump / out/"
```

---

## 5. The two things that would most help

1. **A newer genuine firmware (1.02+).** Card flash, `setup_bis()`, initrd `/etc` is empty so the hook is never read. If one
   exists I can verify model/version/integrity against the decrypter before it goes near a card. **This is the clean fix.**
2. **Which UART is on the 15-pin connector.** If the bootloader prints, we learn where it dies; if it accepts input, we may be able
   to set `/proc/udm/upm_bootmode` to `BIS` or otherwise get a shell with `/setting` writable.

One caveat on (2): soldering to a camera that still powers up and shows menus is the first genuinely irreversible step anyone has
proposed. I'd rather it be your call than mine.
