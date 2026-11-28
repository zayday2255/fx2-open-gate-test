"""FX2 1.01: several write steps in ONE service-mode connection (LOCAL, 2026-11-26; not from the kit author).

Why: each step of fx2_apply.py is its own USB session. The camera talks for ~4.5 s per step, but between steps it drops back to a
USB drive and macOS mounts and unmounts its card again (6-15 s each). This runs the same steps inside one connection.

What stays exactly as in the kit:
  - every step is the author's PINNED library (SHA-256 checked before anything starts, and again by the guard on the packet);
  - every step runs through the author's own per-library body, ct6_level1_run.body_run: known-answer read, no library / no result /
    not busy, one upload, remove + confirm, result read and saved;
  - the camera loads each library on the upload, runs its constructor once and dlcloses it (readcheck.c header, finding F409), so
    a later library under the same file name is a fresh load;
  - the result a step leaves on the RAM disk is deleted before the next step only if its SHA-256 is the one just read (--clear-result
    logic of the kit), because every helper creates its result with O_EXCL.
What changes: the guard's rule "one file write per session" becomes "one write per step, and each write must be that step's pinned
library, in the planned order". The batch stops at the first step whose outcome is not DONE or NOTHING TO DO; the stop request is
always sent. A cold boot (battery out 10 s) undoes everything, as with the single steps.

Before a live run: the whole batch runs on the kit's simulated camera, and each library passes the kit's own self-test and refusals.
  python fx2_batch.py og2560 --dry-run
  python fx2_batch.py og2560 --go --firmware-shown 1.01        (run.sh / sudo, from a cold boot on STILL, after a READY check)
"""
import argparse
import contextlib
import io
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
import ct1_common as c  # noqa: E402
import fx2_run as F  # noqa: E402

R = F.R
PLANS = {
    # "check" first: the kit's read-only check runs in the SAME connection, and nothing is written unless it says VERDICT READY for an
    # ILME-FX2 1.01 with every identity check the same. This replaces the separate check session (and the camera's re-plug after it).
    "og2560": ("check", "L13", "H5", "L16", "L19", "S16"),   # the 3840x2560 open gate (fourth kit's og2560), ran on this FX2 2026-11-26
    "squeeze": ("check", "L13", "L5", "S16"),                 # the squeezed open gate (pull request #3)
    "og57": ("check", "L13", "K5", "K16", "K19", "S16"),      # 5.7K, 5760x3840 (fifth kit's og57; one step per session ran on this FX2 2026-11-27)
    # LOCAL: the same plus A16 (De-Squeeze Display 1.3x shows 2.25:1, for 1.5x anamorphic lenses; needs S16 first, which these plans do).
    # A16 alone ran on this FX2 2026-11-27 on top of S16 and showed the 2.25:1 preview.
    "og2560a": ("check", "L13", "H5", "L16", "L19", "S16", "A16"),
    "og57a": ("check", "L13", "K5", "K16", "K19", "S16", "A16"),
}
# The start-up loader (helper_fx2/sdboot, SDBOOT.md; 2026-11-28). Its files go to the camera's RAM disk piece by piece (F.LOADER_STAGE), then:
#   loader_try_*      RAM ONLY: the helper is started once, now, from the RAM copy, as a process outside the camera application. Nothing is
#                     installed. loader_try_check only READS (the test to run first); the others apply that plan as the kit's steps do.
#   loader_install_*  FLASH: the files are copied to /etc/fx2boot and /etc/ld.so.preload is written. Needs --writes-flash.
#   loader_status     read-only; loader_uninstall, loader_off, loader_on: FLASH (they need --writes-flash too).
#   loader_report     read-only: the whole result of every step of the helper's last run, and its log, into the session folder.
# The read-only check runs first in the plans that bring files or install; status, off, on and uninstall need no check: the way back must
# not depend on the camera's state.
_STAGE = ("check",) + tuple(F.LOADER_STAGE)
PLANS.update({"loader_try_%s" % plan: _STAGE + (step, "W30") for plan, step in F.LOADER_PLANS.items()})
PLANS.update({"loader_install_%s" % plan: _STAGE + (step, "W40") for plan, step in F.LOADER_PLANS.items() if plan != "check"})
PLANS.update({"loader_status": ("W42",), "loader_report": ("W43",), "loader_uninstall": ("W41",), "loader_off": ("W58",), "loader_on": ("W59",)})
NO_CHECK_PLANS = ("loader_status", "loader_report", "loader_uninstall", "loader_off", "loader_on")


def what(step):
    return F.WRITE_STEPS[step][2] if step in F.WRITE_STEPS else "the read-only check (fx2read): identity, every site stock or target, nothing written"


FAMILY = None      # live runs: "NTSC" or "PAL", the family the plan's sensor-side step was picked for (set in main)


def step_ok(step, facts):
    s3 = facts["s3"]
    if step in F.WRITE_STEPS:
        return s3["ok"], s3["outcome"]
    ready = (facts.get("header_ok") and s3.get("ready") and not s3.get("identity_differs") and s3.get("identity_same", 0) > 0
             and any(v in s3.get("header", "") for v in ("fx2read_v1 ", "fx2read_v2 ", "fx2read_v3 ", "fx2read_v4 ", "fx2read_v5 ")))
    if ready and FAMILY:
        fam = F.camera_state(s3)["family"].split(" ")[0]
        if fam in ("NTSC", "PAL") and fam != FAMILY:
            return False, "the check reads this camera as %s, but the plan has the %s steps" % (fam, FAMILY)
    return bool(ready), s3.get("verdict", "no verdict")


class StepSession:
    """One step's view of the batch session: its own results; its files saved with the step's name in front (never overwritten)."""

    def __init__(self, parent, step):
        self.parent, self.step, self.results = parent, step, {}

    def log(self, kind, **fields):
        return self.parent.log(kind, step=self.step, **fields)

    def say(self, text):
        self.parent.say(text)

    def save_bytes(self, name, data):
        return self.parent.save_bytes("%s_%s" % (self.step, name), data)

    def save_json(self, name, obj):
        return self.parent.save_json("%s_%s" % (self.step, name), obj)


def point_at(step, lib, sim=None):
    """The runner's module state and the session guard (and the simulated camera's rules, offline) for this step only."""
    F.use(step)                                        # R.LIB, R.LIB_SHA256, R.LEVEL, fx2_run.WHICH
    rules = R.rules(lib)
    g = R.GUARDS[-1]
    g.rules, g._big, g.writes = rules, len(lib) + 7, 0  # one write, of this library only
    g.allow_result_delete = False
    if sim is not None:
        sim.rules = rules


def batch_body(session, camera, plan, libs, sim=None, first_clear=None):
    clear = first_clear
    session.results["steps"] = {}
    for n, step in enumerate(plan, 1):
        lib = libs[step]
        point_at(step, lib, sim)
        R.CLEAR_SHA = clear
        session.say("")
        session.say("=" * 78)
        session.say("Step %d of %d: %s, %s" % (n, len(plan), step, what(step)))
        ss = StepSession(session, step)
        try:
            R.body_run(ss, camera, lib)
        finally:
            ct6 = ss.results.get("ct6", {})
            session.results["steps"][step] = ct6
            if ct6.get("result"):
                session.results["ct6"] = ct6           # the newest result left on the RAM disk: the next normal run deletes it by this SHA
        facts = ct6.get("result")
        if not facts:
            raise c.StopTest("step %s: no result was read; the steps after it were not run" % step)
        facts.pop("_pages", None)
        F.report(ss, facts, step)
        ok, outcome = step_ok(step, facts)
        if not ok:
            raise c.StopTest("step %s: %s; the steps after it were not run%s"
                             % (step, outcome, " (nothing was written)" if step == "check" else ""))
        clear = facts["sha256"]
    session.say("")
    session.say("All %d steps passed in one connection: %s" % (len(plan), " ".join(plan)))


def simulated_check():
    """A READY answer of the read-only check, built for the simulated camera: the header, seven identity lines and the verdict the
    batch requires. Synthetic on purpose, so the offline run needs no saved session (and no camera's own data) on this computer."""
    lines = ["fx2read fx2read_v4 check for ILME-FX2 1.01; read-only (simulated for the offline batch run)"]
    lines += ["identity %d (simulated)  SAME as the 1.01 update" % k for k in range(7)]
    lines += ["VERDICT READY (simulated)", "== done"]
    return ("\n".join(lines) + "\n").encode()


def simulate_batch(plan, libs):
    """The whole batch on the kit's simulated camera (nothing leaves the PC). The check answers with simulated_check()."""
    replay = simulated_check()
    canned = R.run_helper

    def run_helper(data):
        return (replay, "replayed") if F.WHICH == "check" else canned(data)
    c.use_pmca()
    session = c.Session("simulated", write=False, test="CT6")
    F.use(plan[0])
    sim = F.make_sim(libs[plan[0]])
    stopped = None
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            F.run_helper = run_helper
            R.service_session(session, sim, lambda cam: batch_body(session, cam, plan, libs, sim=sim), libs[plan[0]])
        except c.StopTest as exc:
            stopped = str(exc)
        finally:
            F.run_helper = canned
            R.run_helper = canned
    return session, sim, stopped


def offline_checks(plan, libs):
    for step in plan:
        F.use(step)
        R.refusals(libs[step])
        F.selftest(libs[step])
    session, sim, stopped = simulate_batch(plan, libs)
    sent = R.sent(session)
    writes = [e for e in session.events if e["kind"] == "service_out" and e["name"] == "SET_FILE2"]
    problems = []
    if stopped:
        problems.append("stopped: %s" % stopped)
    if sim.unexpected:
        problems.append("unexpected packets: %r" % sim.unexpected)
    if len(writes) != len(plan):
        problems.append("%d library writes, expected %d" % (len(writes), len(plan)))
    if sim.loads != len(plan):
        problems.append("%d loads on the simulated camera, expected %d" % (sim.loads, len(plan)))
    if sent.count("FILE_DELETE2") != 2 * len(plan) - 1:     # each library removed; each earlier result cleared before the next step
        problems.append("%d deletes, expected %d" % (sent.count("FILE_DELETE2"), 2 * len(plan) - 1))
    steps = session.results.get("steps", {})
    for step in plan:
        facts = (steps.get(step) or {}).get("result")
        if not facts or not step_ok(step, facts)[0]:
            problems.append("step %s did not report DONE in simulation" % step)
    if problems:
        raise AssertionError("batch simulation failed: " + "; ".join(problems))
    return session, sent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", choices=sorted(PLANS))
    ap.add_argument("--dry-run", action="store_true", help="checks and the simulated run only; nothing is sent")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-flash", action="store_true", help="needed for a plan with a start-up loader step that can write the camera's flash")
    ap.add_argument("--ntsc", action="store_true", help="the camera is set to NTSC: the plans' own sensor-side steps (L5 / H5 / K5)")
    ap.add_argument("--pal", action="store_true", help="the camera is set to PAL: the PAL sensor-side steps (Q5 / P5 / J5, mode 0x880)")
    a = ap.parse_args()
    import fx2_apply as A
    global FAMILY
    # A start-up loader plan has no sensor-side step of its own to swap: its helper's plan names the family (og2560 / og2560pal), and that
    # helper's steps refuse on a camera of the other family. So no family is chosen (and none is asked for) for a loader plan.
    loader = a.plan.startswith("loader_")
    if loader and (a.ntsc or a.pal):
        raise SystemExit("A start-up loader plan takes no --ntsc / --pal: the family is in the plan's name (loader_..._og2560 or ..._og2560pal). Nothing was sent.")
    family = None if loader else A.choose_family(a, a.go and not a.dry_run)   # --ntsc / --pal, else the newest saved check, else asked (live)
    plan = tuple(A.PAL_STEPS.get(s, s) for s in PLANS[a.plan]) if family == "PAL" else PLANS[a.plan]
    flash = [s for s in plan if s in F.LOADER_FLASH]
    libs = {}
    for step in plan:
        if step not in F.WRITE_STEPS and step != "check":
            raise SystemExit("%s is not a step of this kit. Nothing was sent." % step)
        libs[step] = F.use(step)                       # the pinned build, or it stops here
    session, sent = offline_checks(plan, libs)
    print("FX2 1.01, batch %s (%s): %d steps in one connection: %s" % (a.plan, family or "start-up loader", len(plan), " ".join(plan)))
    for n, step in enumerate(plan, 1):
        print("  %d. %s  %s  (library %s...)" % (n, step, what(step), F.PINS[step][1][:16]))
    print("Offline: every library pinned, the kit's refusals and self-test passed for each, and the whole batch ran on the simulated camera "
          "(%d packets: %d writes, %d deletes)." % (len(sent), sent.count("SET_FILE2"), sent.count("FILE_DELETE2")))
    if flash:
        print("THIS PLAN CAN WRITE THE CAMERA'S FLASH (steps %s). A battery change does not undo that; the plan loader_uninstall does." % " ".join(flash))
    if a.dry_run:
        print("Dry run only: nothing was sent to any device.")
        return
    if flash and not a.writes_flash:
        raise SystemExit("This plan can write the camera's flash: it needs --writes-flash as well. Nothing was sent.")
    if not a.go or a.firmware_shown != F.FIRMWARE:
        raise SystemExit("A live run needs --go and --firmware-shown %s. Nothing was sent." % F.FIRMWARE)
    FAMILY = family                                    # the in-connection check must read the camera as this family (None: a loader plan)
    if plan[0] != "check" and a.plan not in NO_CHECK_PLANS:   # without the in-connection check, the kit's rule: a saved READY check first
        chk = A.last_check()
        if chk is None or not chk[1]:
            raise SystemExit("The newest saved read-only check of this kit %s. Run check_readonly first and get VERDICT READY. Nothing was sent."
                             % ("does not exist" if chk is None else "(%s) does not say READY" % chk[0]))
    if not A.wait_for_drive(True):
        raise SystemExit("The camera did not show up as a USB drive. Nothing was sent.")
    import ct1_stage2_service as service
    # A library of THIS kit left on the service partition by a session that was cut off (seen 2026-11-27: S16's write got no answer, the file
    # stayed, and survives a battery pull) is deleted by the runner's own remove_leftover and the batch goes on. Anything else still stops it.
    R.KNOWN_LIBS.update({pin[1]: pin[0] for pin in F.PINS.values()})
    first_clear = F.last_saved_sha()
    with c.Session("fx2_batch_%s" % a.plan, test="CT6") as session:
        session.results.update(firmware_shown_on_camera=a.firmware_shown, model=F.MODEL, which="batch_" + a.plan, plan=list(plan), family=family,
                               libraries={s: F.PINS[s][1] for s in plan},
                               pc={"platform": platform.platform(), "python": sys.version.split()[0]})
        F.use(plan[0])
        inner = service.connect(session)
        try:
            R.service_session(session, inner, lambda cam: batch_body(session, cam, plan, libs, first_clear=first_clear), libs[plan[0]])
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            done = [s for s in plan if s in F.WRITE_STEPS and (((session.results.get("steps") or {}).get(s) or {}).get("result") or {}).get("s3", {}).get("ok")]
            print("Steps done in this connection: %s." % (" ".join(done) or "none"))
            if a.plan.startswith("loader_"):
                print("RAM: what these steps put on the camera's RAM disk is gone after a battery change (10 seconds)." if not flash else
                      "FLASH: what the steps %s wrote stays through a battery change. The plan loader_uninstall removes it." % " ".join(flash))
                if "W30" in plan:
                    print("The helper now works on its own inside the camera for a few seconds. Read what it did: the plan loader_status.")
            else:
                print("This WROTE to the camera's memory. A cold boot (battery out for 10 seconds) undoes everything written. Keep the camera on.")


if __name__ == "__main__":
    main()
