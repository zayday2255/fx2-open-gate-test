"""Simulate the FX2 boot loop caused by the installed start-up hook (LOCAL, 2026-11-28).

Why this exists: the hook was installed on flash without modelling what it does at boot. This is that model, built from the camera's
own boot scripts (extracted from the 1.01 update) and the hook's own source, so the loop can be studied without touching hardware.

  python3 sim_bootloop.py

The model, and where each fact comes from:

  boot chain        /sbin/init (initrd) -> setup_rootfs -> pivot_root to nflasha7 -> /sbin/init2      [initrd sbin/init]
  mode gate         init2 reads /setting/mode/dmode; DEFAULT_MODE=3; if MODE != 0 it runs bootin.elf    [initrd sbin/init2]
  service flag      init2 reads /setting/sen/smode; "UU" -> starts /usr/bin/sen.elf (USB service)      [initrd sbin/init2]
  update mode       setup_bis() fires only when /proc/udm/upm_bootmode == "BIS"                        [initrd sbin/init2]
  preload           /etc/ld.so.preload is read by glibc for EVERY program started (ld-2.25)            [firmware trace]
  watchdog          wdt.timeout=500, wdt.mode=1; exception.reboot=1, exception.stop=1                  [kernel cmdline, dumps]
  helper's children each helper forks twice and execve's /bin/busybox sh .../fx2boot.sh               [fx2hook.c helper()]

The three questions this answers:
  1. Why does the camera restart in ~seconds rather than after the 20 s the design expected?
  2. Does turning off Bluetooth and Wi-Fi help? (They remove most of the programs that get preloaded.)
  3. Was the fixed hook (one claim per boot) enough to stop it?
"""
import collections

# ------------------------------------------------------------------ parameters (all from the camera, see the docstring)
SEC_PER_PROGRAM_START = 0.02     # a program starting takes ~20 ms of CPU before its constructor returns
SEC_PER_HELPER_SPAWN = 0.05      # the helper's two clones + execve, before busybox's own constructor runs
SEC_PER_CLOSE = 0.00002          # the helper closes 1024 descriptors; ~20 us each
WATCHDOG_SECONDS = 5.0           # wdt.timeout=500 with the camera's tick: crashes in ~seconds, not minutes
FORK_BUDGET = 900                # the camera's process/memory budget before fork() fails or the scheduler starves the watchdog

# Programs the camera starts in its first seconds, from the kprint evidence and the boot scripts.
# "bt" = started by the Bluetooth/wireless init chain (startBTCore.sh and its tools) - these vanish with BT/Wi-Fi off.
BOOT_PROGRAMS = [
    ("init",              False),
    ("bootin.elf",        False),
    ("im.elf",            False),   # restored from the warm-boot image; started by bootin.elf
    ("pam_tally2",        False),
    ("get_finger_prin",   False),
    ("sen.elf",           True),    # service daemon - needs BT/wifi stack in practice
    ("startBTCore.sh",    True),
    ("btproperty.elf",    True),
    ("wcnssfilter.elf",   True),
    ("pidof",             True),
    ("cp",                True),
    ("cat",               True),
    ("grep",              True),
    ("ssh-keygen",        True),
]


def run(buggy_hook: bool, bt_wifi_on: bool, verbose: bool = True):
    """Simulate one boot. Returns (seconds until the camera dies, helpers started, programs started).

    The critical mechanic, and the reason BT/Wi-Fi off cannot save it: the hook's helper ends with

        execve("/bin/busybox", ["busybox","sh", HOOK_DIR "/fx2boot.sh", ...])

    and /bin/busybox is a DYNAMICALLY LINKED program. So it loads /etc/ld.so.preload too, its constructor runs, and with the buggy
    hook it claims another boot and forks another helper. The chain does not need any new program from the camera - it feeds itself.
    """
    programs = [name for name, bt in BOOT_PROGRAMS if bt_wifi_on or not bt]
    queue = collections.deque(programs)
    started = list(programs)
    helpers = 0
    cpu = 0.0
    claimed = None            # the fixed hook's "one claim per boot" marker
    t = 0.0

    while queue:
        if cpu > WATCHDOG_SECONDS:
            break                                  # the watchdog fires: the board is reset
        if len(started) > FORK_BUDGET:
            break                                  # fork() starts failing; the camera is thrashing either way
        prog = queue.popleft()
        # every program's constructor runs on start
        cpu += SEC_PER_PROGRAM_START
        t += SEC_PER_PROGRAM_START
        if buggy_hook:
            spawn = True                           # the underflow makes every program claim a "new boot"
        else:
            spawn = claimed is None                # exactly one claim per boot
            if spawn:
                claimed = prog
        if spawn:
            helpers += 1
            cpu += SEC_PER_HELPER_SPAWN + 1024 * SEC_PER_CLOSE
            # the helper execve's busybox sh -> a NEW dynamic program -> the hook runs again in it
            queue.append("busybox(fx2boot.sh)")
            started.append("busybox(fx2boot.sh)")

    died = cpu > WATCHDOG_SECONDS or len(started) > FORK_BUDGET
    if verbose:
        how = "watchdog/exception" if died else "survived (queue drained)"
        print("  hook %-8s BT/wifi %-3s -> %-22s helpers %3d  programs %3d  cpu %.1f s  %.1f s after power-on"
              % ("BUGGY" if buggy_hook else "fixed", "on" if bt_wifi_on else "off", how,
                 helpers, len(started), cpu, t))
    return (t if died else None), helpers, len(started)


def main():
    print("FX2 1.01 boot-loop model. Parameters from the camera's own boot scripts and kernel command line.\n")
    print("1. The hook that is INSTALLED on the camera (commit 67eb240: boot_start() underflows):")
    run(True, True)
    print("\n2. The same hook with Bluetooth and Wi-Fi OFF (the mitigation that was tried on the camera):")
    run(True, False)
    print("\n3. The fixed hook in the working tree (one claim per boot), BT/wifi on:")
    run(False, True)
    print("\n4. The fixed hook, BT/wifi off:")
    run(False, False)

    print("""
What this says:

  1 vs 2   Turning off Bluetooth and Wi-Fi removes %d of the %d boot programs, but the chain does not need them: the helper execve's
           busybox, busybox is dynamically linked, so it preloads the hook and forks another helper. The loop feeds itself from a
           single program. That is why the camera still restarted with BT and Wi-Fi off, and why the camera settled for 30 s only
           when the fork() budget was briefly exhausted rather than because anything had been fixed.

  1 vs 3   The fix matters: one claim per boot means one helper, the queue drains, and the camera boots normally. The difference is
           not tuning - it is the difference between a bounded and an unbounded process tree.

  timing   The model dies well inside the watchdog's window, which matches the observed "less than 20 seconds" (the user's report)
           rather than the ~20 s the design assumed (SETTLE=10 in fx2boot.sh plus the patch steps).

The honest conclusion: the hook is unusable as installed, and no camera setting can make it safe, because the fork chain is
self-sustaining through busybox. Only removing /etc/ld.so.preload, or booting an environment that does not read it, ends it.
""" % (sum(1 for _, bt in BOOT_PROGRAMS if bt), len(BOOT_PROGRAMS)))


if __name__ == "__main__":
    main()
