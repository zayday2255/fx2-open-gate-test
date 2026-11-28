"""Write this build's loader steps into ..\\..\\fx2_run.py (the block between the two marker lines), from fx2boot_pins.json.

  C:\\Python313\\python.exe -B update_runner.py

The runner keeps every library's SHA-256 in its own source: this only rewrites that block after a rebuild. pins_for_runner.py --check
compares the result with the files.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1] / "fx2_run.py"
BEGIN, END = "# --- loader steps: begin (helper_fx2/sdboot/update_runner.py writes this block)", "# --- loader steps: end"
pins = json.loads((HERE / "fx2boot_pins.json").read_text(encoding="utf8"))
steps = {k: v for k, v in pins["steps"].items() if k.startswith("W")}
lines = [BEGIN,
         '# The start-up loader, build %s ("sdboot": helper_fx2/sdboot/, modding/FX2_SDBOOT.md). W1..W%d bring its files to the camera\'s RAM disk'
         % (pins["build"], len(pins["stage_order"])),
         "# (/tmp_wbshd, nothing on flash), W50..W53 choose what its helper applies (RAM copy), W30 runs the helper once from RAM, W42 reads its status,",
         "# W43 the whole result of every step of the helper's last run (for the session folder);",
         "# W40 INSTALLS it on flash (/etc/fx2boot and /etc/ld.so.preload) and W41 removes it. A step in LOADER_FLASH can write the camera's flash:",
         "# it needs --writes-flash besides --writes-memory. A battery change does not undo a flash step; W41 does.",
         "LOADER_STEPS = {"]
for k, v in steps.items():
    lines.append('    "%s": ("sdboot/%s", "%s", %s),' % (k, v["file"], v["sha256"], json.dumps(v["what"])))
lines += ["}",
          "LOADER_STAGE = (%s)" % ", ".join('"%s"' % s for s in pins["stage_order"]),
          'LOADER_PLANS = {%s}                                    # plan name: the step that chooses it' % ", ".join(
              '"%s": "%s"' % (p, k) for k, v in steps.items() for p in pins["plans"] if v["what"].startswith("RAM only: choose the helper's plan: %s " % p)),
          'LOADER_FLASH = ("W40", "W41", "W58", "W59")',
          'LOADER_BUILD = "%s"' % pins["build"],
          END]
text = RUN.read_bytes().decode("utf8")
nl = "\r\n" if "\r\n" in text else "\n"
block = nl.join(lines)
if BEGIN in text:
    a, b = text.index(BEGIN), text.index(END) + len(END)
    text = text[:a] + block + text[b:]
else:
    anchor = "PINS.update({k: v[:2] for k, v in WRITE_STEPS.items()})"
    assert text.count(anchor) == 1
    text = text.replace(anchor, block + nl + "WRITE_STEPS.update(LOADER_STEPS)" + nl + anchor)
RUN.write_bytes(text.encode("utf8"))
print("fx2_run.py: %d loader steps of build %s written" % (len(steps), pins["build"]))
