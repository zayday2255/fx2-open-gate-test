"""Prepare the offline test of the FX2 start-up loader: build the two stand-in libraries and write the model camera's memory. (2026-11-28)

  C:\\Python313\\python.exe -B prepare_emu.py          (Windows side; then run emu_fx2boot.py inside WSL)

1. Builds, for AArch64 Linux with glibc (zig cc), into emu/out/:
     libosal_uipc.so   model_osal.c: stands in for the camera's message library (the memory manager's queue and the coprocessor cache queue)
     model_kernel.so   model_kernel.c: stands in for the kernel's /dev/pcidma transfer
2. Runs the kit's own emulation of its write libraries (helper_fx2/emu_fx2_write.py, Unicorn) and records, for each step library the helper
   uses, the model camera that emulation builds for it: the coprocessor pages before the step, the bytes the step may change (each site's
   stock and new value), and the pages after it. emu_fx2boot.py puts the same pages into its coprocessor memory file, runs the same libraries
   through the camera's real loader with fx2cp.so, and must end with the same memory.
   Written to emu/out/model_<name>.json; the image itself (cpapp-b.bin at 0x108000) is read from the extracted firmware by emu_fx2boot.py.
"""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent
KIT = SD.parent
ROOT = KIT.parents[2]
OUT = HERE / "out"
ZIG = [str(ROOT / "work/venv_zig/Scripts/python.exe"), "-m", "ziglang", "cc", "-target", "aarch64-linux-gnu.2.25", "-O1", "-Wall", "-Wextra", "-fPIC", "-shared", "-g0", "-s"]
STEPS = ("L13", "H5", "P5", "L5", "L16", "S16")


def cc(src, out, soname):
    r = subprocess.run(ZIG + ["-Wl,-soname," + soname, str(HERE / src), "-o", str(OUT / out)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("STOP: %s did not compile:\n%s" % (src, r.stderr[-4000:]))
    for stray in ((OUT / out).with_suffix(".lib"), (OUT / out).with_suffix(".pdb")):
        stray.unlink(missing_ok=True)


def main():
    OUT.mkdir(exist_ok=True)
    cc("model_osal.c", "libosal_uipc.so", "libosal_uipc.so")
    cc("model_kernel.c", "model_kernel.so", "model_kernel.so")
    sys.path.insert(0, str(KIT))
    sys.path.insert(0, str(KIT.parent / "helper"))
    sys.path.insert(0, str(ROOT / "build"))
    import emu_fx2_write as W
    want = {hashlib.sha256((KIT / ("libJit_fx2_%s.so" % s)).read_bytes()).hexdigest(): s for s in STEPS}
    caps = {}
    init0, go0 = W.Run.__init__, W.Run.go

    def init(self, libbytes, files, dirs, mem, allowed, lose=None):
        init0(self, libbytes, files, dirs, mem, allowed, lose)
        self._cap = (hashlib.sha256(libbytes).hexdigest(), mem, dict(allowed), mem.snapshot(), lose)

    def go(self):
        r = go0(self)
        h, mem, allowed, before, lose = self._cap
        step = want.get(h)
        text = self.writes.get(W.RESULT, b"").decode("utf8", "replace")
        def was(a):                                   # the byte before the run: a page the model made, else the image, else zero
            p = before.get(a & ~0xFFF)
            if p is not None:
                return p[a & 0xFFF]
            o = a - W.BASE
            return mem.image[o] if 0 <= o < len(mem.image) else 0
        stock = all(was(a) == pr[0] for a, pr in allowed.items()) if allowed else False
        # the first run of each library on a stock model camera that ends DONE: "apply on stock"
        if step and step not in caps and lose is None and not self.bad and stock and any(ln.startswith("DONE: ") for ln in text.split("\n")):
            caps[step] = {"step": step, "library_sha256": h, "result": text,
                          "before": {"%x" % a: p.hex() for a, p in sorted(before.items())},
                          "after": {"%x" % a: bytes(p).hex() for a, p in sorted(mem.snapshot().items())},
                          "allowed": {"%x" % a: [pr[0], pr[1]] for a, pr in sorted(allowed.items())}}
        return r

    W.Run.__init__, W.Run.go = init, go
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = W.main()
    lines = buf.getvalue().splitlines()
    print("emu_fx2_write.py: %d checks, %s" % (sum(1 for ln in lines if ln.startswith(("PASS", "FAIL"))), lines[-1] if lines else "no output"))
    if rc:
        raise SystemExit("STOP: the kit's own emulation fails; nothing was written")
    for s in STEPS:
        if s not in caps:
            raise SystemExit("STOP: no 'apply on stock' run of %s was seen in emu_fx2_write.py" % s)
        c = caps[s]
        (OUT / ("model_%s.json" % s)).write_text(json.dumps(c) + "\n", encoding="utf8", newline="\n")
        done = next(ln for ln in c["result"].split("\n") if ln.startswith("DONE: "))
        print("%-4s %3d pages before, %3d after, %4d bytes may change   %s" % (s, len(c["before"]), len(c["after"]), len(c["allowed"]), done))
    # 3. The kit's own model camera for its read-only check (helper_fx2/emu_fx2.py), stock, for an NTSC-set and a PAL-set camera, with what
    #    the kit's check (libJit_fx2_check.so, as loaded INSIDE the camera application) reports for it. emu_fx2boot.py gives the same memory to
    #    X0, the check built for OUTSIDE the application, which must report the same lines.
    import emu_fx2 as K
    kit_check = (KIT / "libJit_fx2_check.so").read_bytes()
    for name, kw in (("check", {}), ("check_pal", {"pal": "stock"})):
        files, _dirs, _phys, cp, _own = K.model(**kw)
        run, text = K.run(kit_check, **kw)
        if run.bad or "VERDICT READY" not in text:
            raise SystemExit("STOP: the kit's check does not say READY for its own model camera (%s): %s" % (name, run.bad))
        (OUT / ("model_%s.json" % name)).write_text(json.dumps({
            "ram": [["%x" % a, bytes(b).hex()] for a, b in cp["ram"].items()],          # in the model's own order: a later block lies over an earlier one
            "image_sha256": hashlib.sha256(cp["image"]).hexdigest(),
            "cmdline": files["/proc/cmdline"].decode(), "kit_check_result": text}) + "\n", encoding="utf8", newline="\n")
        print("%-9s %3d RAM blocks; the kit's check inside the application: %s" % (name, len(cp["ram"]), next(ln for ln in text.split("\n") if ln.startswith("VERDICT"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
