#!/usr/bin/env python3
"""Offline test of the FX2 1.01 start-up loader: the built files run under the camera's own dynamic loader, C library and shell. (2026-11-28)

  From Windows:   C:\\Python313\\python.exe -B prepare_emu.py      then
                  wsl.exe -e python3 "/mnt/c/.../helper_fx2/sdboot/emu/emu_fx2boot.py" [--only A,B,...] [--keep]

It needs Linux (WSL), qemu-aarch64 and debugfs; no root. What is real and what is a stand-in:
  REAL   the camera's files from the 1.01 update: /lib/ld-2.25.so, libc, /bin/busybox and its applets, /usr/bin/startBTCore.sh, /version.txt,
         libmpr.so, av-cam.bin, cpapp-b.bin; the kit's step libraries (byte for byte the pinned files); every file this folder builds
         (fx2hook.so, fx2cp.so, fx2boot.sh, X0, X18/X19/X20, the W steps), unchanged.
  REAL   the Linux kernel underneath for files, processes, pipes, /proc/<pid>/maps and /proc/<pid>/mem (qemu-aarch64 runs each AArch64
         program as a Linux process; a private binfmt_misc entry inside a user namespace makes the shell's own exec calls work).
  STAND-IN  the camera application: fake_im.py, a process named im.elf that maps libmpr.so, libsencore.so and libJiritsu.so (the camera's files)
  STAND-IN  the camera's libosal_uipc.so (model_osal.c) and the kernel's /dev/pcidma transfer (model_kernel.c); coprocessor memory is a file
         holding cpapp-b.bin and the model camera of the kit's own emulation (prepare_emu.py); /dev/mem is a file with av-cam.bin at its
         physical address; /sys/kernel/debug/suspend_stats is a file the test writes; /etc is a folder (on the camera: a FAT partition);
         /proc/cmdline is the kit's model command line (it names the memory reserved for av-cam.bin, as the camera's does).
  NOT TESTED HERE  anything about the camera itself: whether its message library works from a process of its own, when the coprocessor is
         ready after power-on, the FAT partition's behaviour, timing.
Writes evidence/fx2/sdboot_emu.txt (every check) when run from the map.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent
KIT = SD.parent
ROOT = KIT.parents[2]
DEV = ROOT / "work/extracted/fx2_101/0700_part_image/dev"
WORK = Path.home() / "a7iv/fx2boot_emu"
SYS = WORK / "root"
BASE, AVCAM_PHYS, BUF_PHYS = 0x108000, 0x401000000, 0x47F000000
PRELOAD_TEXT = b"/etc/fx2boot/fx2hook.so\n"
RES = "tmp_wbshd/readcheck_result.txt"
results = []


def sha(b):
    return hashlib.sha256(b).hexdigest()


def ok(cond, text):
    results.append((bool(cond), text))
    print(("PASS  " if cond else "FAIL  ") + text, flush=True)
    return bool(cond)


def show(*texts):
    if "--debug" in sys.argv:
        for x in texts:
            print("DEBUG| " + str(x).replace("\n", "\nDEBUG| "), flush=True)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- the sandbox

def reexec_in_namespace():
    """Run this script again as root of a new user + mount namespace (no real privilege), where it may mount, chroot and register binfmt_misc."""
    os.execvp("unshare", ["unshare", "-r", "-m", sys.executable, str(Path(__file__).resolve()), "--inside"] + sys.argv[1:])


def build_sysroot():
    initrd = Path.home() / "a7iv/initrd_main_fx2_101/root"
    if not initrd.is_dir():
        r = sh(["bash", str(ROOT / "build/wsl_unpack_main_initrd.sh"), "fx2_101"])
        if not initrd.is_dir():
            raise SystemExit("STOP: the FX2 initrd could not be unpacked:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    if SYS.exists():
        shutil.rmtree(SYS)
    shutil.copytree(initrd, SYS, symlinks=True)
    for d in ("usr/bin", "usr/lib", "etc", "tmp", "tmp_wbshd", "tmp_bt", "emu", "dev", "proc", "sys/kernel/debug", "setting/mode"):
        (SYS / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(DEV / "nflasha15/bin/startBTCore.sh", SYS / "usr/bin/startBTCore.sh")
    shutil.copy(DEV / "nflasha15/lib/libmpr.so", SYS / "usr/lib/libmpr.so")
    shutil.copy(DEV / "nflasha15/lib/libsencore.so", SYS / "usr/lib/libsencore.so")       # the camera's own: present, and must NOT get loaded
    shutil.copy(DEV / "nflasha15/lib/libJiritsu.so", SYS / "usr/lib/libJiritsu.so")
    (SYS / "emu/cmdline").write_text(json.loads((HERE / "out/model_check.json").read_text())["cmdline"] + "\n")
    shutil.copy(HERE / "out/libosal_uipc.so", SYS / "usr/lib/libosal_uipc.so")            # stand-in
    shutil.copy(HERE / "out/model_kernel.so", SYS / "emu/model_kernel.so")                # stand-in
    # the Bluetooth daemon the camera's script starts: here a script that only stays alive for a moment
    (SYS / "usr/bin/btproperty.elf").write_text("#!/bin/sh\nsleep 3\n")
    for p in ("usr/bin/startBTCore.sh", "usr/bin/btproperty.elf"):
        os.chmod(SYS / p, 0o755)
    for p in (SYS / "bin").iterdir():
        if p.is_file() and not p.is_symlink():
            os.chmod(p, 0o755)
    for p in (SYS / "lib").iterdir():
        if p.is_file() and not p.is_symlink():
            os.chmod(p, 0o755)
    (SYS / "dev/null").write_bytes(b"")
    (SYS / "dev/pcidma").write_bytes(b"")
    if not (SYS / "version.txt").is_file():
        shutil.copy(DEV / "nflasha7/version.txt", SYS / "version.txt")


def enter_sandbox():
    magic = b"\\x7fELF\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\xb7\\x00"
    mask = b"\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff"
    qemu = shutil.which("qemu-aarch64")
    r = sh(["mount", "-t", "binfmt_misc", "none", "/proc/sys/fs/binfmt_misc"])
    if r.returncode:
        raise SystemExit("STOP: binfmt_misc could not be mounted in the namespace: " + r.stderr)
    with open("/proc/sys/fs/binfmt_misc/register", "wb") as f:
        f.write(b":qemu-aarch64:M::" + magic + b":" + mask + b":" + qemu.encode() + b":FP")
    for src, dst in (("/proc", SYS / "proc"), ("/dev/null", SYS / "dev/null")):
        r = sh(["mount", "--rbind" if src == "/proc" else "--bind", src, str(dst)])
        if r.returncode:
            raise SystemExit("STOP: %s could not be bound into the sandbox: %s" % (src, r.stderr))
    r = sh(["mount", "--bind", str(SYS / "emu/cmdline"), str(SYS / "proc/cmdline")])
    if r.returncode:
        raise SystemExit("STOP: the model kernel command line could not be bound over /proc/cmdline in the sandbox: " + r.stderr)


def cam(cmd, env=None, timeout=120, stdin=None):
    """Run a command line with the camera's shell inside the sandbox, with the environment the camera application hands its children."""
    e = {"PATH": "/sbin:/bin:/usr/sbin:/usr/bin", "HOME": "/"}
    e.update(env or {})
    return subprocess.run(["chroot", str(SYS), "/bin/busybox", "sh", "-c", cmd], capture_output=True, text=True, env=e, timeout=timeout, stdin=stdin)


def reset_camera(files_too=True):
    """A camera as the firmware ships it: nothing in /etc, an empty RAM disk, no logs of the stand-ins."""
    for d in ("etc", "tmp_wbshd", "tmp_bt", "emu", "tmp", "setting/mode"):
        for p in (SYS / d).iterdir():
            if d == "emu" and p.name in ("model_kernel.so", "cpram.base", "devmem.base", "cmdline"):
                continue
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (SYS / "tmp/jiritsu").mkdir(parents=True, exist_ok=True)


def power_on(n):
    (SYS / "sys/kernel/debug/suspend_stats").write_text("success: %d\nfail: 0\nfailed_freeze: 0\nfailed_prepare: 0\n" % n)


def kit_step(step, folder=SD, leave=False):
    """What the kit's runner makes the camera do with one step library: write it as /tmp/jiritsu/libJit.so, load it once, fetch and remove
    the result, remove the library. Loading = the dynamic loader running the library's constructor; here in a small process of its own."""
    lib = SYS / "tmp/jiritsu/libJit.so"
    shutil.copy(folder / ("libJit_fx2_%s.so" % step), lib)
    r = cam("LD_PRELOAD=/tmp/jiritsu/libJit.so /bin/busybox true")
    lib.unlink()
    res = SYS / RES
    text = res.read_text(errors="replace") if res.is_file() else ""
    if res.is_file() and not leave:          # leave: the last step of a kit session, whose result stays until the next session
        res.unlink()
    return text, r


def outcome(text):
    lines = text.split("\n")
    pick = lambda s: next((ln for ln in lines if ln.startswith(s)), None)
    if pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"):
        return "UNDO INCOMPLETE"
    return ("DONE" if pick("DONE: ") else "NOTHING TO DO" if pick("NOTHING TO DO") else "NOT DONE" if pick("NOT DONE: ")
            else "NOTHING WRITTEN" if any("nothing is written" in ln for ln in lines) else "UNKNOWN")


def tree(d):
    """Every file under a sandbox folder with its SHA-256 (the folder's whole state)."""
    out = {}
    for p in sorted((SYS / d).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(SYS))] = sha(p.read_bytes())
        elif p.is_dir():
            out[str(p.relative_to(SYS)) + "/"] = "dir"
    return out


# ---------------------------------------------------------------- the model camera

def load_models():
    m = {}
    for s in ("L13", "H5", "P5", "L5", "L16", "S16"):
        c = json.loads((HERE / "out" / ("model_%s.json" % s)).read_text())
        c["before"] = {int(a, 16): bytes.fromhex(h) for a, h in c["before"].items()}
        c["after"] = {int(a, 16): bytes.fromhex(h) for a, h in c["after"].items()}
        c["allowed"] = {int(a, 16): tuple(v) for a, v in c["allowed"].items()}
        m[s] = c
    return m


def image_byte(image, a):
    o = a - BASE
    return image[o] if 0 <= o < len(image) else 0


def merged_pages(models, steps, image):
    """One coprocessor memory holding every listed step's model camera. A byte two models set differently (and differently from the image)
    stops the test."""
    pages = {}
    for s in steps:
        for a, p in models[s]["before"].items():
            if a not in pages:
                pages[a] = bytearray(p)
                continue
            q = pages[a]
            for k in range(4096):
                if p[k] != q[k]:
                    base = image_byte(image, a + k)
                    if q[k] == base:
                        q[k] = p[k]
                    elif p[k] != base:
                        raise SystemExit("STOP: the model cameras of %s disagree at 0x%x" % (steps, a + k))
    return pages


def make_cpram(pages, image):
    base = SYS / "emu/cpram.base"
    if not base.is_file():
        with open(base, "wb") as f:
            f.seek(BASE)
            f.write(image)
            f.truncate(0x10000000)
    cp = SYS / "emu/cpram.bin"
    shutil.copy(base, cp)
    with open(cp, "r+b") as f:
        for a, p in pages.items():
            f.seek(a)
            f.write(p)


def cp_read(a, n):
    with open(SYS / "emu/cpram.bin", "rb") as f:
        f.seek(a)
        return f.read(n)


def make_devmem(av):
    p = SYS / "dev/mem"
    if p.exists():
        p.unlink()
    with open(p, "wb") as f:
        f.seek(AVCAM_PHYS)
        f.write(av)
        f.truncate(BUF_PHYS + 0x10000)


def av_now(n):
    with open(SYS / "dev/mem", "rb") as f:
        f.seek(AVCAM_PHYS)
        return f.read(n)


class App:
    """The stand-in camera application."""

    def __init__(self, lm_bytes, name="im.elf", file_bytes=None):
        """file_bytes: what libmpr.so on disk holds when the application's memory (lm_bytes) differs from it (an applied encoder side)."""
        (SYS / "usr/lib/libmpr.so").write_bytes(file_bytes or lm_bytes)
        env = dict(os.environ)
        if file_bytes:
            (SYS / "emu/lm_memory").write_bytes(lm_bytes)
            env["FAKE_IM_MEMORY"] = str(SYS / "emu/lm_memory")
        self.p = subprocess.Popen([sys.executable, str(HERE / "fake_im.py"), str(SYS / "usr/lib/libmpr.so"), name,
                                   str(SYS / "usr/lib/libsencore.so"), str(SYS / "usr/lib/libJiritsu.so")], stdout=subprocess.PIPE, text=True, env=env)
        pid, addr, size = self.p.stdout.readline().split()
        self.pid, self.addr, self.size = int(pid), int(addr, 16), int(size)

    def memory(self):
        with open("/proc/%d/mem" % self.pid, "rb") as f:
            f.seek(self.addr)
            return f.read(self.size)

    def stop(self):
        self.p.send_signal(signal.SIGKILL)
        self.p.wait()


def wait_for_end(tag, seconds=90, runs=1):
    """Wait until the helper of power-on `tag` has written its END line `runs` times (or the time is up); returns that helper's lines."""
    log = SYS / "tmp_wbshd/fx2boot.log"
    mark = "fx2boot[%s]: " % tag
    t0 = time.time()
    mine = []
    while time.time() - t0 < seconds:
        if log.is_file():
            mine = [ln for ln in log.read_text(errors="replace").split("\n") if mark in ln or ln.startswith(("hook: ", "fx2cp: "))]
            if sum(1 for ln in mine if mark + "END" in ln) >= runs and not (SYS / "tmp_wbshd/fx2boot.busy").exists():
                break
        time.sleep(0.5)
    return "\n".join(mine)


def bad_lines():
    out = []
    for n in ("osal.log", "pcidma.log"):
        p = SYS / "emu" / n
        if p.is_file():
            out += [ln for ln in p.read_text().split("\n") if "BAD" in ln]
    return out


def cp_writes():
    """Every byte a transfer towards the coprocessor changed, from the stand-in's log: {address: (old, new)} (first old, last new)."""
    out = {}
    p = SYS / "emu/pcidma.log"
    if not p.is_file():
        return out
    for ln in p.read_text().split("\n"):
        if "  byte 0x" in ln:
            a, rest = ln.split("byte ")[1].split(": ")
            o, n = rest.split(" -> ")
            a = int(a, 16)
            out[a] = (out[a][0] if a in out else int(o, 16), int(n, 16))
    return out


# ---------------------------------------------------------------- the tests

def install_files(plan, stage_only=False):
    """The kit's steps in order: the pieces (W1..), a plan, and the install. Returns the result texts."""
    pins = json.loads((SD / "fx2boot_pins.json").read_text())
    texts = [kit_step(s)[0] for s in pins["stage_order"]]
    texts.append(kit_step({"check": "W50", "og2560": "W51", "og2560pal": "W52", "squeeze": "W53"}[plan])[0])
    if not stage_only:
        texts.append(kit_step("W40")[0])
    return texts


def test_kit_steps(pins):
    print("== B: the kit steps (pieces to the RAM disk, plan, install, status, off switch, uninstall)")
    reset_camera()
    power_on(1)
    stock = (tree("etc"), tree("setting"))
    t, _ = kit_step("W42")
    ok(outcome(t) == "DONE" and "/etc/ld.so.preload: absent" in t and "installed copy, /etc/fx2boot: absent" in t and "RAM copy, /tmp_wbshd/fx2boot: absent" in t
       and (tree("etc"), tree("setting")) == stock, "W42 status on a stock camera: nothing installed, nothing on the RAM disk; flash untouched")
    t, _ = kit_step("W40")
    ok(outcome(t) == "NOTHING WRITTEN" and (tree("etc"), tree("setting")) == stock, "W40 install with no files on the RAM disk: refused, flash untouched")
    t, _ = kit_step("W30")
    ok(outcome(t) == "NOTHING WRITTEN" and not (SYS / "tmp_wbshd/fx2boot.log").exists(), "W30 run now with no files on the RAM disk: refused, nothing started")
    two = [s for s in pins["stage_order"] if "piece 2 of" in pins["steps"][s]["what"]]
    t, _ = kit_step(two[0])
    ok(outcome(t) == "NOTHING WRITTEN" and "send the pieces in order" in t, "%s (a second piece) before its first piece: refused" % two[0])
    texts = [kit_step(s)[0] for s in pins["stage_order"]]
    staged = {n: sha((SYS / "tmp_wbshd/fx2boot" / n).read_bytes()) for n in pins["files"] if (SYS / "tmp_wbshd/fx2boot" / n).is_file()}
    ok(all(outcome(x) == "DONE" for x in texts) and staged == {n: v["sha256"] for n, v in pins["files"].items()} and (tree("etc"), tree("setting")) == stock,
       "W1..W%d: every piece DONE, the %d files on the RAM disk are the build's byte for byte; flash untouched" % (len(texts), len(staged)))
    t, _ = kit_step("W30")
    ok(outcome(t) == "NOTHING WRITTEN" and "no known plan" in t, "W30 run now without a plan: refused")
    t, _ = kit_step("W40")
    ok(outcome(t) == "NOTHING WRITTEN" and "no known plan" in t and (tree("etc"), tree("setting")) == stock, "W40 install without a plan: refused, flash untouched")
    t, _ = kit_step("W51")
    ok(outcome(t) == "DONE" and (SYS / "tmp_wbshd/fx2boot/plan").read_bytes() == b"og2560" and (tree("etc"), tree("setting")) == stock,
       "W51 plan og2560: written to the RAM copy only (the loader is not installed)")
    f = SYS / "tmp_wbshd/fx2boot/libJit_fx2_L16.so"
    good = f.read_bytes()
    f.write_bytes(good[:100] + bytes([good[100] ^ 1]) + good[101:])
    t, _ = kit_step("W40")
    ok(outcome(t) == "NOTHING WRITTEN" and "libJit_fx2_L16.so: NOT this build's file" in t and (tree("etc"), tree("setting")) == stock,
       "W40 install with one bit of one RAM file changed: refused, flash untouched")
    f.write_bytes(good)
    (SYS / "etc/ld.so.preload").write_bytes(b"/etc/fx2_preload_marker.so")
    t, _ = kit_step("W40")
    ok(outcome(t) == "NOTHING WRITTEN" and "run the uninstall step first" in t and (SYS / "etc/ld.so.preload").read_bytes() == b"/etc/fx2_preload_marker.so"
       and not (SYS / "etc/fx2boot").exists(), "W40 install while /etc/ld.so.preload holds another build's line: refused, that file untouched")
    (SYS / "etc/ld.so.preload").unlink()
    power_on(0)
    t, _ = kit_step("W40")
    ok(outcome(t) == "NOTHING WRITTEN" and "count of suspends" in t and (tree("etc"), tree("setting")) == stock,
       "W40 install where the kernel's suspend count reads 0 (the hook could never start anything): refused")
    power_on(1)
    (SYS / "tmp_wbshd/fx2boot.g1").write_bytes(b"")              # this power-on is taken: no helper starts while the kit steps run
    t, _ = kit_step("W40")
    etc = tree("etc")
    want = {"etc/fx2boot/": "dir", "etc/ld.so.preload": sha(PRELOAD_TEXT), "etc/fx2boot/plan": sha(b"og2560")}
    want.update({"etc/fx2boot/" + n: v["sha256"] for n, v in pins["files"].items()})
    ok(outcome(t) == "DONE" and etc == want and tree("setting") == stock[1],
       "W40 install: /etc holds exactly the %d files, the plan and ld.so.preload = %r; nothing else on flash changed" % (len(pins["files"]), PRELOAD_TEXT.decode()))
    t, _ = kit_step("W42")
    ok(outcome(t) == "DONE" and "the start-up hook is INSTALLED" in t and "=> every file is this build's" in t and "plan: og2560" in t and tree("etc") == etc,
       "W42 status: INSTALLED, every file this build's, plan og2560; flash untouched")
    t, _ = kit_step("W52")
    ok(outcome(t) == "DONE" and (SYS / "etc/fx2boot/plan").read_bytes() == b"og2560" and (SYS / "tmp_wbshd/fx2boot/plan").read_bytes() == b"og2560pal" and tree("etc") == etc,
       "W52 plan og2560pal on an installed loader: the RAM copy's plan changes, the installed one stays (flash untouched)")
    t, _ = kit_step("W40")
    ok(outcome(t) == "DONE" and (SYS / "etc/fx2boot/plan").read_bytes() == b"og2560pal" and "already held this loader's line" in t,
       "W40 again: the installed copy is renewed with the RAM copy's plan (og2560pal); ld.so.preload was already this loader's")
    t1, _ = kit_step("W58")
    t2, _ = kit_step("W58")
    off = (SYS / "etc/fx2boot/off").is_file()
    t3, _ = kit_step("W59")
    ok(outcome(t1) == "DONE" and outcome(t2) == "NOTHING TO DO" and off and outcome(t3) == "DONE" and not (SYS / "etc/fx2boot/off").exists(),
       "W58 / W59: the off switch is made, made again (nothing to do), removed")
    f = SYS / "etc/fx2boot/fx2cp.so"
    f.write_bytes(f.read_bytes()[:-1] + b"\x00\x01")
    t, _ = kit_step("W42")
    ok("fx2cp.so: NOT this build's file" in t and "the installed copy is NOT complete" in t, "W42 status with a damaged installed file: says so")
    # what earlier research builds left, as the contributor's branch made it
    for n in ("fx2_preload_marker.so", "fx2_any", "fx2_imelf", "fx2in_cat", "fx2in_startBTCore.sh", "fx2_preload_ran"):
        (SYS / "etc" / n).write_bytes(b"ok\n")
    (SYS / "setting/mode/preload").write_bytes(b"/setting/fx2_preload_marker.so")
    (SYS / "etc/other_file").write_bytes(b"not ours")
    t, _ = kit_step("W41")
    ok(outcome(t) == "DONE" and tree("etc") == {"etc/other_file": sha(b"not ours")} and tree("setting") == stock[1] and not (SYS / "tmp_wbshd/fx2boot").exists(),
       "W41 uninstall: ld.so.preload, /etc/fx2boot, the earlier builds' files and the RAM copy are gone; a file that is not ours stays")
    (SYS / "etc/other_file").unlink()
    t, _ = kit_step("W41")
    ok(outcome(t) == "DONE" and (tree("etc"), tree("setting")) == stock, "W41 again on a clean camera: DONE, nothing to remove; flash as shipped")
    (SYS / RES).write_bytes(b"an earlier result")
    lib = SYS / "tmp/jiritsu/libJit.so"
    shutil.copy(SD / "libJit_fx2_W41.so", lib)
    cam("LD_PRELOAD=/tmp/jiritsu/libJit.so /bin/busybox true")
    lib.unlink()
    ok((SYS / RES).read_bytes() == b"an earlier result", "a step loaded while an earlier result is still there: does nothing at all (the kit's rule)")
    (SYS / RES).unlink()


def bt_run(env=None):
    """The camera's own Bluetooth start script, as the camera application runs it after a power-on."""
    for p in (SYS / "tmp_bt").iterdir():
        p.unlink()
    t0 = time.time()
    r = cam("/usr/bin/startBTCore.sh; echo rc=$?; cat /tmp_bt/bsa_s_pid | grep -c '^[0-9][0-9]*$'", env=env)
    return r.stdout.strip(), r.stderr.strip(), time.time() - t0


def test_hook(pins):
    print("== C: the start-up hook in the camera's own programs")
    reset_camera()
    power_on(1)
    base_out, base_err, base_t = bt_run()
    ok(base_out == "rc=0\n1" and not base_err, "baseline, nothing installed: the camera's startBTCore.sh ends 0 with one pid in /tmp_bt/bsa_s_pid (%.1f s)" % base_t)
    (SYS / "tmp_wbshd/fx2boot.g1").write_bytes(b"")
    install_files("check")
    (SYS / "tmp_wbshd/fx2boot.g1").unlink()
    shutil.rmtree(SYS / "tmp_wbshd/fx2boot")
    for p in (SYS / "tmp_wbshd").glob("fx2boot*"):
        p.unlink()
    ok((SYS / "etc/ld.so.preload").read_bytes() == PRELOAD_TEXT, "installed for the hook tests (plan check; no camera application in the sandbox, so the helper only waits)")

    power_on(0)
    out, err, t = bt_run({"LD_DEBUG": "files", "LD_DEBUG_OUTPUT": "/tmp/ld"})
    inits = [p for p in (SYS / "tmp").glob("ld.*") if "calling init: /etc/fx2boot/fx2hook.so" in p.read_text(errors="replace")]
    names = sorted({ln.split("file=")[1].split(" ")[0] for p in inits for ln in p.read_text(errors="replace").split("\n") if "file=" in ln and "[0];  needed by" not in ln and "generating link map" in ln and "fx2hook" not in ln and "/lib/" not in ln and "/usr/lib" not in ln})
    marks = sorted(p.name for p in (SYS / "tmp_wbshd").iterdir())
    ok(out == base_out and not err and len(inits) >= 5 and not marks,
       "cold boot (suspend count 0): the hook's constructor ran in %d programs of the script and did nothing: no mark, no log, no helper; the script's result is the baseline's" % len(inits))
    for p in (SYS / "tmp").glob("ld.*"):
        p.unlink()

    power_on(1)
    out, err, t = bt_run({"LD_DEBUG": "files", "LD_DEBUG_OUTPUT": "/tmp/ld"})
    inits = [p for p in (SYS / "tmp").glob("ld.*") if "calling init: /etc/fx2boot/fx2hook.so" in p.read_text(errors="replace")]
    time.sleep(2)
    log = (SYS / "tmp_wbshd/fx2boot.log").read_text() if (SYS / "tmp_wbshd/fx2boot.log").is_file() else ""
    marks = sorted(p.name for p in (SYS / "tmp_wbshd").iterdir() if p.name.startswith("fx2boot.g"))
    ok(out == base_out and not err and len(inits) >= 5 and marks == ["fx2boot.g1"] and log.count("START") == 1 and "fx2boot[1]: plan check: X0 X18" in log,
       "power-on 1: the hook ran in %d programs, ONE of them started the helper once (mark fx2boot.g1, one START line); the script's result is the baseline's (%.1f s against %.1f s)" % (len(inits), t, base_t))
    for p in (SYS / "tmp").glob("ld.*"):
        p.unlink()
    out, err, t = bt_run()
    time.sleep(1)
    log = (SYS / "tmp_wbshd/fx2boot.log").read_text()
    ok(out == base_out and log.count("START") == 1, "the same power-on, the script run again: no second helper")
    helper_alive = sh(["pgrep", "-f", "fx2boot.sh /etc/fx2boot 1"]).stdout.split()
    t0 = time.time()
    r = cam("echo hello | cat | grep -c hello")
    ok(r.stdout.strip() == "1" and time.time() - t0 < 5 and helper_alive,
       "while the helper is alive (waiting for the camera application): a pipeline of the camera's programs ends at once, no descriptor of theirs is held")
    wait_for_end(1, 60)
    log = (SYS / "tmp_wbshd/fx2boot.log").read_text()
    ok("the camera application (im.elf) was not found in 30 s" in log and "END: nothing more is done" in log and not (SYS / "tmp_wbshd/fx2boot.busy").exists()
       and tree("etc") == {**{"etc/fx2boot/": "dir", "etc/ld.so.preload": sha(PRELOAD_TEXT), "etc/fx2boot/plan": sha(b"check")}, **{"etc/fx2boot/" + n: v["sha256"] for n, v in pins["files"].items()}},
       "no camera application: the helper gives up after 30 s, says so, removes its busy mark; flash untouched")

    power_on(2)
    (SYS / "etc/fx2boot/off").write_bytes(b"")
    out, err, t = bt_run()
    time.sleep(1)
    log = (SYS / "tmp_wbshd/fx2boot.log").read_text()
    ok(out == base_out and "hook: switched off by /etc/fx2boot/off; nothing started, power-on 2" in log and log.count("START") == 1 and (SYS / "tmp_wbshd/fx2boot.g2").exists(),
       "power-on 2 with the off switch: the hook starts nothing and says so")
    (SYS / "etc/fx2boot/off").unlink()

    power_on(3)
    f = SYS / "etc/fx2boot/fx2boot.sh"
    good = f.read_bytes()
    f.write_bytes(good + b"\n")
    out, err, t = bt_run()
    time.sleep(1)
    log = (SYS / "tmp_wbshd/fx2boot.log").read_text()
    ok(out == base_out and "hook: not this build's file, nothing started: fx2boot.sh" in log and log.count("START") == 1,
       "power-on 3 with one installed file changed by one byte: the hook starts nothing and names the file")
    f.write_bytes(good)

    power_on(4)
    hook = SYS / "etc/fx2boot/fx2hook.so"
    good = hook.read_bytes()
    hook.unlink()
    out, err, t = bt_run()
    ok(out == base_out and "cannot be preloaded" in err and "ignored" in err and not (SYS / "tmp_wbshd/fx2boot.g4").exists(),
       "the hook file missing: the camera's loader says 'cannot be preloaded ... ignored' and every program runs as in the baseline")
    hook.write_bytes(b"")
    out, err, t = bt_run()
    ok(out == base_out and "cannot be preloaded" in err and not (SYS / "tmp_wbshd/fx2boot.g4").exists(),
       "the hook file empty: the same, every program runs as in the baseline")
    # THE HAZARD of this kind of hook, shown so that it is known: a hook file that is cut short is NOT ignored
    died = []
    for cut in (1000, 3000, 6000):
        hook.write_bytes(good[:cut])
        r = cam("/bin/busybox true; echo rc=$?")
        died.append("rc=0" not in r.stdout)
    ok(all(died), "HAZARD, as the camera's loader behaves: a hook file cut short (1000, 3000, 6000 of %d bytes) is not ignored, the program is killed at start. "
                  "This is why the install step never writes the hook in place (new name, read back, SHA-256, rename) and writes ld.so.preload last" % len(good))
    hook.write_bytes(good)
    kit_step("W41")
    out, err, t = bt_run()
    ok(out == base_out and not err and tree("etc") == {}, "after W41 uninstall: the script runs as in the baseline, nothing is preloaded, /etc is empty")


def expected_cp(models, steps, pages):
    want = {a: bytearray(p) for a, p in pages.items()}
    allowed = {}
    for s in steps:
        for a, (o, n) in models[s]["allowed"].items():
            allowed[a] = (o, n)
    return allowed


def check_cp(models, steps, image, label):
    """After a run: every byte the steps may change holds its new value, and the stand-in's log shows no other byte changed."""
    allowed = {}
    for s in steps:
        allowed.update(models[s]["allowed"])
    new_ok = all(cp_read(a, 1)[0] == n for a, (o, n) in allowed.items())
    w = cp_writes()
    differ = {a for a, (o, n) in allowed.items() if o != n}             # a site's bytes that are the same in stock and design are not "changed"
    stray = [a for a, (o, n) in w.items() if a not in allowed or n != allowed[a][1] or o != allowed[a][0]]
    return ok(new_ok and not stray and set(w) == differ and not bad_lines(),
              "%s: all %d site bytes of %s hold the designs' values; the transfer log shows exactly the %d that differ from stock changed, stock to new, and no malformed request"
              % (label, len(allowed), "+".join(steps), len(differ)))


def test_helper(pins):
    print("== D: the helper with the model camera (the kit's step libraries through fx2cp.so; the encoder step from outside)")
    models = load_models()
    image = (DEV / "nflasha8/cpapp-b.bin").read_bytes()
    av = (DEV / "nflasha3/av-cam.bin").read_bytes()
    lm = (DEV / "nflasha15/lib/libmpr.so").read_bytes()
    design = json.loads((ROOT / "modding/designs/ogfile2560_hs_s_fx2_v2.json").read_text(encoding="utf8"))
    av2, lm2 = bytearray(av), bytearray(lm)
    n_av = n_lm = 0
    for p in design["patches"]:
        o, new = int(p["file_off"], 16), bytes.fromhex(p["new"])
        if p["binary"] == "av-cam.bin":
            av2[o:o + len(new)] = new
            n_av += 1
        else:
            lm2[o:o + len(new)] = new
            n_lm += 1
    av2, lm2 = bytes(av2), bytes(lm2)
    for s, c in models.items():                     # the recorded model: after = before with exactly the allowed bytes new
        after = {a: bytearray(p) for a, p in c["after"].items()}
        same = all(after[a & ~0xFFF][a & 0xFFF] == n for a, (o, n) in c["allowed"].items())
        ok(same, "model camera of %s (from the kit's emulation): after its DONE run every one of its %d bytes holds the new value" % (s, len(c["allowed"])))

    def camera(steps, av_bytes=av, lm_bytes=lm):
        make_cpram(merged_pages(models, steps, image), image)
        make_devmem(av_bytes)
        return App(lm_bytes)

    def boot(n, plan, expect_run=True):
        """Power-on number n with the loader installed: the first program the camera starts triggers the hook."""
        for p in (SYS / "emu").glob("*.log"):
            p.unlink()
        power_on(n)
        cam("/bin/busybox true")
        if not expect_run:
            time.sleep(3)
        return wait_for_end(n, 120 if expect_run else 1)

    def install(plan):
        reset_camera()
        power_on(1)
        (SYS / "tmp_wbshd/fx2boot.g1").write_bytes(b"")
        texts = install_files(plan)
        (SYS / "tmp_wbshd/fx2boot.g1").unlink()
        # the stand-in for the kernel's transfer driver is preloaded beside the hook (on the camera the driver is in the kernel)
        (SYS / "etc/ld.so.preload").write_bytes(PRELOAD_TEXT + b"/emu/model_kernel.so\n")
        return all(outcome(t) == "DONE" for t in texts)

    # D1: battery change on an NTSC camera, plan og2560
    ok(install("og2560"), "installed with plan og2560")
    app = camera(("L13", "H5", "L16", "S16"))
    flash = tree("etc")
    log = boot(1, "og2560")
    steps = [ln.split("]: ")[1] for ln in log.split("\n") if "]: " in ln]
    ok("END: plan og2560, every step done" in log and all(any(x.startswith(s + ": DONE: ") for x in steps) for s in ("L13", "H5", "L16", "X19", "S16")),
       "power-on 1 (after a battery change), plan og2560: L13, H5, L16, X19, S16 each DONE, in that order")
    check_cp(models, ("L13", "H5", "L16", "S16"), image, "coprocessor memory")
    ok(av_now(len(av)) == av2 and app.memory() == lm2, "encoder side, from outside the application: av-cam.bin holds its %d sites and the application's libmpr.so its %d, every other byte unchanged" % (n_av, n_lm))
    ok(tree("etc") == flash, "the helper wrote no flash")
    x19 = (SYS / "tmp_wbshd/fx2boot_X19.txt").read_text(errors="replace")
    ok("outside build: the camera application is process %d" % app.pid in x19 and "libmpr.so mapped at 0x%x" % app.addr in x19 and x19.startswith("readcheck 1 level 19\neuid 0\n"),
       "X19 found the camera application by name (process %d) and its libmpr.so mapping (0x%x) in /proc" % (app.pid, app.addr))
    dbg = cam("rm -f /tmp/ld.*; LD_DEBUG=files LD_DEBUG_OUTPUT=/tmp/ld LD_PRELOAD='/etc/fx2boot/fx2cp.so /etc/fx2boot/libJit_fx2_S16.so' /bin/busybox true; cat /tmp/ld.*; rm -f /tmp_wbshd/readcheck_result.txt")
    ok("/usr/lib/libsencore.so" not in dbg.stdout + dbg.stderr and "file=/etc/fx2boot/fx2cp.so" in dbg.stdout + dbg.stderr and "libosal_uipc.so" in dbg.stdout + dbg.stderr,
       "the camera's loader took fx2cp.so where the step library asks for libsencore.so: the camera's own /usr/lib/libsencore.so (present) was not opened")

    # D2: the same power-on again; then a switch-off with the battery in (coprocessor memory stock again, the main processor's kept)
    log2 = boot(1, "og2560", expect_run=False)
    ok(log2.count("START") == 1, "the same power-on, another program started: no second helper run")
    make_cpram(merged_pages(models, ("L13", "H5", "L16", "S16"), image), image)
    log = boot(2, "og2560")
    steps = [ln.split("]: ")[1] for ln in log.split("\n") if "fx2boot[2]: " in ln]
    ok("END: plan og2560, every step done" in log and any(x.startswith("X19: NOTHING TO DO") for x in steps) and sum(1 for x in steps if ": DONE: " in x) == 4,
       "power-on 2 (switch off and on, battery in: coprocessor memory stock again, encoder side still in place): four steps DONE, X19 NOTHING TO DO")
    check_cp(models, ("L13", "H5", "L16", "S16"), image, "coprocessor memory after power-on 2")
    ok(av_now(len(av)) == av2 and app.memory() == lm2, "encoder side unchanged by power-on 2")

    # D3: the result file of the kit's last session is still on the RAM disk (it stays there until the kit's next session)
    make_cpram(merged_pages(models, ("L13", "H5", "L16", "S16"), image), image)
    (SYS / RES).write_bytes(b"the last result of a kit session")
    log = boot(3, "og2560")
    ok("the kit's result file is set aside for this run" in log and "END: plan og2560, every step done" in log
       and (SYS / RES).read_bytes() == b"the last result of a kit session" and not (SYS / "tmp_wbshd/fx2boot.kitresult").exists(),
       "power-on 3 with the kit's last result file still there: the helper sets it aside, runs the plan, and puts it back byte for byte")
    check_cp(models, ("L13", "H5", "L16", "S16"), image, "coprocessor memory after power-on 3")
    (SYS / RES).unlink()

    # D4: the plan cannot be finished (here: the coprocessor's cache call fails) while the encoder side is still in place from before:
    # the state the kit warns about (encoder side applied, the rest stock). The helper puts the encoder side back.
    (SYS / "emu/fail_cache").write_bytes(b"")
    log = boot(4, "og2560")
    ok("L13: not done" in log and "the encoder side is put back to stock (X20)" in log and "X20: DONE" in log and "END: the plan was not finished; the encoder side is stock" in log
       and not cp_writes() and av_now(len(av)) == av and app.memory() == lm,
       "power-on 4, the first step cannot be done while the encoder side is in place: nothing written to the coprocessor, and X20 puts av-cam.bin and the application's libmpr.so back to stock, byte for byte")
    (SYS / "emu/fail_cache").unlink()
    fx = (SYS / "tmp_wbshd/fx2boot.log").read_text()
    ok("fx2cp: cache: the coprocessor answered 0" in fx, "fx2cp.so wrote the reason to the log")

    # D5: other firmware
    v = (SYS / "version.txt").read_bytes()
    (SYS / "version.txt").write_bytes(b"45002_02.2026010101\n")
    log = boot(5, "og2560")
    ok("the camera's firmware is not the one this build was made for" in log and not cp_writes(), "power-on 5 with another firmware's /version.txt: the helper stops at once, nothing is written")
    (SYS / "version.txt").write_bytes(v)
    app.stop()

    # D6: the wrong plan for the camera (an NTSC plan on a PAL-set camera): the sensor step refuses
    ok(install("og2560"), "installed with plan og2560 (for a PAL-set model camera)")
    app = camera(("L13", "P5", "L16", "S16"))
    log = boot(1, "og2560")
    ok("L13: DONE" in log and "H5: not done" in log and "X20: NOTHING TO DO" in log and "END: the plan was not finished; the encoder side is stock" in log
       and set(cp_writes()) == {a for a, (o, n) in models["L13"]["allowed"].items() if o != n} and av_now(len(av)) == av and app.memory() == lm,
       "plan og2560 on a PAL-set camera: L13 done, H5 refuses (as the kit's does there), the helper stops: only L13's bytes changed, the encoder side is checked stock (X20: nothing to do)")
    app.stop()

    # D7: PAL
    ok(install("og2560pal"), "installed with plan og2560pal")
    app = camera(("L13", "P5", "L16", "S16"))
    log = boot(1, "og2560pal")
    ok("END: plan og2560pal, every step done" in log, "PAL-set model camera, plan og2560pal: L13, P5, L16, X19, S16 each DONE")
    check_cp(models, ("L13", "P5", "L16", "S16"), image, "coprocessor memory (PAL)")
    ok(av_now(len(av)) == av2 and app.memory() == lm2, "encoder side (PAL): as designed")
    app.stop()

    # D8: squeeze
    ok(install("squeeze"), "installed with plan squeeze")
    app = camera(("L13", "L5", "S16"))
    log = boot(1, "squeeze")
    ok("END: plan squeeze, every step done" in log and "X20: NOTHING TO DO" in log, "plan squeeze: X20 (nothing to do), L13, L5, S16 each DONE")
    check_cp(models, ("L13", "L5", "S16"), image, "coprocessor memory (squeeze)")
    ok(av_now(len(av)) == av and app.memory() == lm, "plan squeeze leaves the encoder side stock")
    app.stop()
    app = camera(("L13", "L5", "S16"), av2, lm2)
    log = boot(2, "squeeze")
    ok("END: plan squeeze, every step done" in log and "X20: DONE" in log and av_now(len(av)) == av and app.memory() == lm,
       "plan squeeze on a camera whose encoder side was still in place: X20 puts it back first, then L13, L5, S16")
    app.stop()

    # D9: the read-only plan: X0 (the kit's check built for outside the application) and X18
    def camera_check(model, av_bytes=av, lm_bytes=lm):
        """The kit's own model camera for its check: the image and the RAM blocks of helper_fx2/emu_fx2.py, in the model's order. The
        application's memory holds lm_bytes; libmpr.so on disk is always the firmware's file, as on a camera."""
        assert model["image_sha256"] == sha(image)
        make_cpram({}, image)
        with open(SYS / "emu/cpram.bin", "r+b") as f:
            for a_, h in model["ram"]:
                f.seek(int(a_, 16))
                f.write(bytes.fromhex(h))
        make_devmem(av_bytes)
        return App(lm_bytes, file_bytes=lm if lm_bytes != lm else None)

    def facts(text):
        """The lines of a check result that state what the camera holds, without the addresses a mapping happens to have."""
        out = []
        for ln in text.split("\n"):
            if ln.startswith(("page ", "site ", "other ", "guard ", "av ", "  bytes ", "places not", "VERDICT")):
                out.append(ln)
            elif ln.startswith("lm "):
                out.append(ln.split(" at ")[0] + " " + ln.split(" bytes ", 1)[-1])
        return out

    def said(log, n):
        return [ln.split("]: ", 1)[1] for ln in log.split("\n") if "fx2boot[%s]: X0: " % n in ln]

    def result(name):
        p = SYS / "tmp_wbshd" / name
        return p.read_text(errors="replace") if p.is_file() else ""

    chk = json.loads((HERE / "out/model_check.json").read_text())
    chk_pal = json.loads((HERE / "out/model_check_pal.json").read_text())
    ok(install("check"), "installed with plan check (read-only)")
    app = camera_check(chk)
    log = boot(1, "check")
    c1, x18 = result("fx2boot_X0.txt"), result("fx2boot_X18.txt")
    ok("END: plan check, every step done" in log and not cp_writes() and av_now(len(av)) == av and app.memory() == lm and not bad_lines(),
       "plan check: both steps ran; no transfer towards the coprocessor, av-cam.bin and the application's libmpr.so untouched")
    ok("== level 18 verdict: READY: every guard is as in the file and every site holds the stock bytes" in x18,
       "X18, from outside the application, on a stock camera: READY (every guard as in the file, every site stock)")
    reads = [ln for ln in (SYS / "emu/pcidma.log").read_text().split("\n") if " read " in ln] if (SYS / "emu/pcidma.log").is_file() else []
    ok(c1.startswith("fx2read fx2read_v5 check for ILME-FX2 1.01; read-only\noutside build %s: " % pins["build"]) and "camera application: process %d\n" % app.pid in c1
       and "== file /proc/%d/maps\n" % app.pid in c1 and "/usr/lib/libmpr.so" in c1 and len(reads) > 5 and c1.rstrip().endswith("== done"),
       "X0, the kit's check built for outside: it found the camera application (process %d), took ITS list of mappings, and made %d coprocessor reads through fx2cp.so"
       % (app.pid, len(reads)))
    ok("VERDICT READY" in c1 and "places not as the 1.01 update or not read: 0" in c1 and "NOT MAPPED" not in c1 and "NOT READ" not in c1,
       "X0 on a stock camera, from outside: VERDICT READY, 0 places not as the 1.01 update (the kit's own check counts 9 there: 3 files and 6 libmpr.so sites it looks for in its own process)")
    want = facts(chk["kit_check_result"])
    ok(facts(c1) == want and len(want) > 60,
       "X0 from outside states what the kit's check states INSIDE the application for the same camera: all %d lines equal (code pages, sites, files, libmpr.so, av-cam.bin, verdict)" % len(want))
    d = said(log, 1)
    n = lambda pre, end: sum(1 for ln in c1.split("\n") if ln.startswith(pre) and ln.endswith(end))
    ok(any(x.startswith("X0: read; VERDICT READY") for x in d)
       and "X0: coprocessor buffer (memory manager, through fx2cp.so): buffer physical 0x%010x handle" % BUF_PHYS in "\n".join(d)
       and "X0: coprocessor code pages: %d same, 0 differ" % n("page ", "SAME as the 1.01 update") in d
       and any(x.startswith("X0: coprocessor sites: %d stock, 0 target, 0 test, 0 other, 0 not read, " % n("site ", "  STOCK")) for x in d)
       and "X0: application files: 3 same, 0 differ, 0 not mapped" in d and "X0: libmpr.so sites: 6 stock, 0 target, 0 other, 0 not read" in d
       and "X0: av-cam.bin: guards %d same, 0 differ; sites %d stock, 0 target, 0 other" % (n("guard ", "  SAME"), n("av ", "  STOCK")) in d
       and "X0: places not as the 1.01 update or not read: 0" in d and n("page ", "SAME as the 1.01 update") >= 4 and n("site ", "  STOCK") > 20,
       "the helper's log says what X0 read, in %d lines: the buffer the memory manager gave, code pages, sites, files, libmpr.so, av-cam.bin, the count" % len(d))
    show("\n".join(d))
    t, _ = kit_step("W42")
    show(t[t.find("the helper's reports"):][:2500])
    ok(outcome(t) == "DONE" and "fx2boot_X0.txt:\n    camera application: process %d\n" % app.pid in t and "    buffer physical 0x%010x handle" % BUF_PHYS in t
       and "    VERDICT READY" in t and "X0: coprocessor sites: " in t,
       "W42 status after it: X0's buffer line, its count and its verdict, and the helper's log with the lines above")
    t, _ = kit_step("W43")
    body = [ln for ln in t.split("\n")]
    clean = lambda s: "".join(ch if " " <= ch <= "~" else "." for ch in s)
    ok(outcome(t) == "DONE" and "==== fx2boot.log: " in t and "==== fx2boot_X0.txt: %d bytes\n" % len(c1.encode()) in t and "==== end of fx2boot_X18.txt" in t
       and all(("| " + clean(ln)) in body for ln in c1.split("\n")[:-1]) and all(("| " + clean(ln)) in body for ln in x18.split("\n")[:-1])
       and sum(1 for ln in body if ln.startswith(("DONE", "NOT DONE", "NOTHING", "!!", "UNDO"))) == 1 and body[-2].startswith("== done"),
       "W43 report: the log and the whole of both results (%d + %d bytes), every line behind '| '; its one outcome line is its own" % (len(c1), len(x18)))
    ok(tree("etc") == {**{"etc/fx2boot/": "dir", "etc/ld.so.preload": sha(PRELOAD_TEXT + b"/emu/model_kernel.so\n"), "etc/fx2boot/plan": sha(b"check")},
                       **{"etc/fx2boot/" + n_: v["sha256"] for n_, v in pins["files"].items()}}, "the read-only plan, W42 and W43 wrote no flash")
    # the read-only checks on a camera whose encoder side is applied
    app.stop()
    app = camera_check(chk, av2, lm2)
    log = boot(2, "check")
    c2, x18 = result("fx2boot_X0.txt"), result("fx2boot_X18.txt")
    ok("== level 18 verdict: APPLIED" in x18, "X18 on a camera whose encoder side is applied: APPLIED")
    show("\n".join(said(log, 2)), "\n".join(ln for ln in c2.split("\n") if ln.startswith(("VERDICT", "places", "lm ", "!!"))), "av TARGET %d" % sum(1 for ln in c2.split("\n") if ln.startswith("av ") and ln.endswith("  TARGET")))
    ok("VERDICT READY" in c2 and "X0: libmpr.so sites: 0 stock, 6 target, 0 other, 0 not read" in said(log, 2) and "X0: application files: 3 same, 0 differ, 0 not mapped" in said(log, 2) and app.memory() == lm2 and sum(1 for ln in c2.split("\n") if ln.startswith("av ") and ln.endswith("  TARGET")) == n_av,
       "X0 there (libmpr.so on disk stock, the application's memory changed): VERDICT READY, its 6 libmpr.so sites and av-cam.bin's %d read TARGET, through the memory file and /dev/mem" % n_av)
    app.stop()
    # a PAL-set camera (the first camera this ran on is one)
    app = camera_check(chk_pal)
    log = boot(3, "check")
    c3 = result("fx2boot_X0.txt")
    want = facts(chk_pal["kit_check_result"])
    show("\n".join("- " + x for x in want if x not in facts(c3)), "\n".join("+ " + x for x in facts(c3) if x not in want), "\n".join(said(log, 3)))
    ok("VERDICT READY" in c3 and facts(c3) == want and any(ln.startswith("other pal_stored_record ") for ln in c3.split("\n")),
       "X0 on a PAL-set model camera (a real PAL FX2's stored records): VERDICT READY, all %d lines as the kit's check states them inside the application" % len(want))
    # what the log shows when the camera's memory manager does not serve a process outside the application (the open question of issue 16)
    (SYS / "emu/fail_dmm").write_bytes(b"")
    log = boot(4, "check")
    c4 = result("fx2boot_X0.txt")
    d = said(log, 4)
    (SYS / "emu/fail_dmm").unlink()
    ok("X0: read; VERDICT NOT READY" in d and "X0: coprocessor buffer (memory manager, through fx2cp.so): !! buffer allocation failed; no coprocessor reads" in d
       and "X0: coprocessor code pages: 0 same, 0 differ" in d and "X0: application files: 3 same, 0 differ, 0 not mapped" in d
       and "fx2cp: " in log and "END: plan check, every step done" in log and "VERDICT NOT READY" in c4 and not cp_writes(),
       "the memory manager refuses the buffer: the log names it (buffer allocation failed, fx2cp's own line, 0 code pages), the files and libmpr.so are still read, verdict NOT READY")
    app.stop()

    # D10: two processes named im.elf
    app = camera(("L13", "H5", "L16", "S16"))
    app2 = App(lm)
    log = boot(5, "check")
    ok("more than one process is named im.elf" in log and not cp_writes(), "two processes named im.elf: the helper stops, nothing is read or written")
    app2.stop()
    app.stop()
    kit_step("W41")

    # D11: "run now" from the RAM copy, nothing installed
    reset_camera()
    power_on(1)
    stock = tree("etc")
    install_files("og2560", stage_only=True)
    (SYS / "etc/ld.so.preload").write_bytes(b"/emu/model_kernel.so\n")      # only the stand-in for the kernel's transfer driver
    app = camera(("L13", "H5", "L16", "S16"))
    t, _ = kit_step("W30", leave=True)
    log = wait_for_end("usb", 60)
    ok(outcome(t) == "DONE" and "fx2boot[usb]: END: plan og2560, every step done" in log and "waiting" not in log,
       "W30 run now (RAM copy, loader not installed): the helper ran plan og2560 at once, every step DONE")
    ok((SYS / RES).is_file() and (SYS / RES).read_text(errors="replace") == t and "the kit's result file is set aside for this run" in log,
       "W30's own result file (which the kit leaves in place) was set aside for the run and is back unchanged")
    (SYS / RES).unlink()
    check_cp(models, ("L13", "H5", "L16", "S16"), image, "coprocessor memory (run now)")
    (SYS / "etc/ld.so.preload").unlink()
    ok(av_now(len(av)) == av2 and app.memory() == lm2 and tree("etc") == stock, "run now: encoder side as designed; flash untouched")
    t, _ = kit_step("W42")
    ok(outcome(t) == "DONE" and "fx2boot[usb]: END: plan og2560, every step done" in t and "X19: DONE" in t.replace("fx2boot_X19.txt:\n    == level 19: apply", "X19: DONE"),
       "W42 status afterwards shows the helper's log and each step's outcome line")
    app.stop()


def main():
    if "--inside" not in sys.argv:
        if not (HERE / "out/model_S16.json").is_file():
            raise SystemExit("STOP: run prepare_emu.py first (Windows side)")
        reexec_in_namespace()
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    WORK.mkdir(parents=True, exist_ok=True)
    build_sysroot()
    enter_sandbox()
    pins = json.loads((SD / "fx2boot_pins.json").read_text())
    r = cam("echo `cat /version.txt`; /bin/busybox 2>&1 | grep -m1 BusyBox")
    ok(r.returncode == 0 and "45002_02.2025101101" in r.stdout and "BusyBox" in r.stdout,
       "sandbox: the camera's busybox and loader run (%s)" % " | ".join(r.stdout.strip().split("\n")))
    try:
        if not only or "B" in only:
            test_kit_steps(pins)
        if not only or "C" in only:
            test_hook(pins)
        if not only or "D" in only:
            test_helper(pins)
    finally:
        sh(["pkill", "-f", "fake_im.py"])
    bad = [t for good, t in results if not good]
    print("ALL PASS (%d checks)" % len(results) if not bad else "FAILED: %d of %d" % (len(bad), len(results)))
    ev = ROOT / "evidence/fx2"
    if ev.is_dir() and not only:
        (ev / "sdboot_emu.txt").write_text("emu_fx2boot.py, build %s, %s\n" % (pins["build"], time.strftime("%Y-%m-%d %H:%M:%S"))
                                           + "".join(("PASS  " if g else "FAIL  ") + t + "\n" for g, t in results)
                                           + ("ALL PASS (%d checks)\n" % len(results) if not bad else "FAILED: %d of %d\n" % (len(bad), len(results))))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
