"""Print (or check) the LOADER_STEPS block of fx2_run.py from fx2boot_pins.json.

  C:\\Python313\\python.exe -B pins_for_runner.py            prints the block to paste into fx2_run.py
  C:\\Python313\\python.exe -B pins_for_runner.py --check    fails unless fx2_run.py holds exactly these pins and the files have them
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
pins = json.loads((HERE / "fx2boot_pins.json").read_text(encoding="utf8"))
steps = {k: v for k, v in pins["steps"].items() if k.startswith("W")}
if "--check" in sys.argv:
    sys.path.insert(0, str(HERE.parents[1]))
    import fx2_run
    bad = []
    for k, v in steps.items():
        got = fx2_run.WRITE_STEPS.get(k)
        if not got or got[0] != "sdboot/" + v["file"] or got[1] != v["sha256"] or got[2] != v["what"]:
            bad.append("%s: fx2_run.py does not hold this build's pin" % k)
        if hashlib.sha256((HERE / v["file"]).read_bytes()).hexdigest() != v["sha256"]:
            bad.append("%s: the file is not the one fx2boot_pins.json names" % k)
    extra = [k for k in fx2_run.LOADER_STEPS if k not in steps]
    if extra:
        bad.append("fx2_run.py has loader steps this build does not: %s" % extra)
    for n, v in pins["files"].items():
        if hashlib.sha256((HERE / n).read_bytes()).hexdigest() != v["sha256"]:
            bad.append("%s: the file is not the one fx2boot_pins.json names" % n)
    # The hook compiles the manifest in, so a stale fx2hook.so refuses every boot ("not this build's file, nothing started").
    # It was reused once during a rebuild and shipped exactly that way (2026-11-28); this check makes that impossible to miss.
    import struct
    hook = (HERE / "fx2hook.so").read_bytes()
    for n, v in pins["files"].items():
        if n == "fx2hook.so":
            continue                  # a file cannot hold its own hash; fx2boot_hookfile.h carries that record, checked below
        found = False
        for i in range(len(hook) - 76):
            if hook[i:i + 40].split(b"\0")[0] == n.encode() and struct.unpack_from("<I", hook, i + 40)[0] == v["size"] \
                    and hook[i + 44:i + 76].hex() == v["sha256"]:
                found = True
                break
        if not found:
            bad.append("fx2hook.so: its built-in manifest does not hold %s at %d bytes - rebuild the hook" % (n, v["size"]))
    self_rec = 'static const struct fx2boot_file fx2boot_hook = { "fx2hook.so", %d, { ' % len(hook)
    if self_rec not in (HERE / "fx2boot_hookfile.h").read_text(encoding="utf8"):
        bad.append("fx2boot_hookfile.h does not hold fx2hook.so at %d bytes - rebuild the hook" % len(hook))
    print("\n".join(bad) if bad else "fx2_run.py holds the %d loader steps of build %s, and every file has its pinned SHA-256" % (len(steps), pins["build"]))
    sys.exit(1 if bad else 0)
print("LOADER_STEPS = {")
for k, v in steps.items():
    print('    "%s": ("sdboot/%s", "%s", %s),' % (k, v["file"], v["sha256"], json.dumps(v["what"])))
print("}")
print("LOADER_STAGE = (%s)" % ", ".join('"%s"' % s for s in pins["stage_order"]))
