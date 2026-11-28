"""FX2 (ILME-FX2) firmware 1.01: apply, or put back, the open-gate state in the camera's MEMORY.

  python fx2_apply.py apply    [--no-screen] [--no-meta] [--dry-run] [--no-movie-session]
  python fx2_apply.py putback  [--no-screen] [--dry-run]
  python fx2_apply.py screen | screen-putback  [--dry-run]
  python fx2_apply.py test1 | test2 | test3 | test4  [--dry-run]       (second and third kit, 2026-11-26: the diagnostic ladder)
  python fx2_apply.py squeeze  [--dry-run]             (the squeezed open gate: ran on an FX2, 2026-11-26)
  python fx2_apply.py test5 | test6 | og2560 | test7  [--dry-run]      (fourth kit, 2026-11-26: the path to a true 3840x2560 file)
  python fx2_apply.py putback-2560 | putback-hold  [--dry-run]         (put back og2560 / test7 without a cold boot)
  python fx2_apply.py og57 | putback-57  [--dry-run]                    (2026-11-27: the 5760x3840 state, 300 Mbps; GitHub issue 7)
  python fx2_apply.py og2560si | og57si | putback-2560si | putback-57si (the same with XAVC S-I 4K as well)
  add --pal or --ntsc to any of these but screen / screen-putback / test1 (fifth kit, 2026-11-27): which sensor-side steps to use. Without
  either, the newest saved check says it (fx2read_v5 reads it from the camera's records), or the script asks.

The FX2 counterpart of fx3_apply.py (the FX3 kit, which records open gate on two FX3s). The FX2 is the A7 IV's sensor (IMX710 class)
on the A7C II's platform, so its open-gate steps are the A7 IV kit's (its default state since 2026-11-18, true 3840x2560 files of the
whole 3:2 sensor area in XAVC HS 4K and XAVC S 4K at 24p, with the MP4 header fix since 2026-11-24), ported to the FX2 1.01 and
checked against the FX2's own code in emulation. On FX2s set to NTSC the squeezed open gate (squeeze: GitHub issue 1) and the true
3840x2560 file (og2560: issue 5, XAVC HS 4K and XAVC S 4K, a 10-minute clip, playback, HDMI, the 3:2 rear screen) WORK (2026-11-26).

  NTSC or PAL (fifth kit, 2026-11-27). On a PAL-set FX2 4K 25p runs drive mode 0x880, whose stored record comes from the 50 Hz input table;
  the sensor-side steps L5 / H5 are made for mode 0x880's NTSC sibling 0x8c0 (23.98p) and refuse on PAL (nothing is written; a PAL
  camera's dump showed it). The PAL steps are the same designs moved to mode 0x880: Q5 (ogsq880_fx2_v1, for L5; the A7 IV's ogsq880_v1,
  which works on a PAL A7 IV) and P5 (ogh2560880_fx2_v1, for H5), put back by Q6 / P6. Every other step is the same on NTSC and PAL
  (L19 covers 25p as well as 23.98p). With --pal the targets use them: og2560 = L13 + P5 + L16 + L19 + S16, squeeze = L13 + Q5 + S16.
  Both WORK on an FX2 set to PAL (GitHub issue 5, 2026-11-26): 3840x2560 and the squeezed 3840x2160 at 25.000 fps in XAVC S 4K, SteadyShot
  Active too. On PAL the FX2's XAVC HS 4K is 50p only, so PAL means XAVC S 4K 25p.

  apply    five steps, each its own USB session: L13 raw write buffer (dmmwb4688_fx2_v1), L5 sensor side (ogsq_fx2_v1), L16 output size
           (outsz2560_fx2_v1), L19 encoder side with the MP4 headers (ogfile2560_hs_s_fx2_v2), S16 rear screen at 3:2 with the focus frames
           and the camera's own De-Squeeze Display set for the 3:2 picture (lcd32dsq_fx2_v1). Afterwards: XAVC HS 4K or XAVC S 4K at
           23.98p only. With --no-screen only the first four; with --no-meta the encoder step without the MP4 header heights (N19).
           A step that finds its bytes already applied says NOTHING TO DO and counts as passed.
  putback  the reverse: S17, L20, L17, L6, L14 (with --no-screen the last four). A cold boot (battery out for 10 seconds) also undoes everything.
  screen / screen-putback   only the screen step (S16) or its put back (S17).
  test1    SECOND KIT (2026-11-26), after the first FX2 test: every step applied, but entering MOVIE ended in the coprocessor's forced
           exception "FW: S-Ele Refresh ng force exception" (0x507da0: a stage still busy for 11 frames, the A7 IV's F662 signature) and a
           restart. Test 1 = L13 + B5 (fhband_fx2_v1, the A7 IV's fhband_v1, F658): the sensor in the same full-height mode as L5, but the
           stage keeps its stock 16:9 height. Then one read-only dump on MOVIE (sensor mode, the memory manager's workspace: which write
           buffer was opened, and at what size).
  test2    L13 + L5 only (the A7 IV's two-step squeezed baseline, F682): the 4,688-row stage, no output-size, encoder or screen step. Then
           one read-only dump on MOVIE, or, if the camera restarts, after the restart (the kprint record and the snapshot image's head).
           Tests start from a cold boot on STILL. To undo: battery out for 10 seconds.
  test3    THIRD KIT (2026-11-26), after test 2 worked on the FX2 (steady picture, clips recorded, sensor column 5, the 4,688-row stage with the
           whole 7008x4672 window, L13's 33,003,520-byte write buffer in use): L13 + L5 + L16, the output size. Then the dump on MOVIE (v3 reads the
           saved output records: size, format code, type) or, after a restart, the crash record.
  test4    L13 + L5 + L16 + L19: test 3 and the encoder side (the full open gate without the screen step).
  squeeze  L13 + L5 + S16 (a tester's pull request, 2026-11-26; ran on an FX2): test 2 plus the screen step. The file is 3840x2160 holding the
           whole 3:2 sensor area squeezed 27/32 vertically; the 3:2 rear screen shows it at its true shape. No output-size or encoder step.

  FOURTH KIT (2026-11-26). Test 3 crashed on the FX2: L16 is the first failing step (on the A7 IV it never crashed). Read from the FX2's
  code and emulated (build/emu_rcinput_fx2.py): its resize set-up 0x51fbc0 raises the first-scaler size it hands the second scaler to at
  least the output size (0xbd3a32; only the FX2 and the A1 II have that code). With L16 that is 4336x2560, while L5's records make the
  first scaler give 4336x2438. The A7 IV's design for a 4336x2560 first scaler, ogh2560_v1 (F712, F713), is ported as H5 and takes L5's place.
  test5    L13 + H5: the taller first-scaler picture with the stock output size. Expected: what test 2 gives (squeezed 3840x2160 clips).
  test6    L13 + H5 + L16: plus the output size. A DIAGNOSTIC STEP ONLY: do not press REC. The encoder is still set for 2,160 rows,
           and on an FX2 (GitHub issue 5) a recording in this state froze the camera until the battery was pulled.
  og2560   L13 + H5 + L16 + L19 + S16: THE 3840x2560 PATH. Expected: clips of 3840x2560 with 2,560 real rows, the 3:2 rear screen filled.
  test7    L13 + L5 + F16 + L16 + L19, THE FALLBACK, for the case that test5 does not run: F16 is one code word that makes the resize
           set-up keep the records' first-scaler size, so the second scaler enlarges 2,438 rows to 2,560 as on the A7 IV. No screen step.
  For all four: APS-C/Super 35 Off, S&Q and Proxy off. SteadyShot Off for a first run; with og2560 SteadyShot Active works on an FX2
  (issue 5: the margin raises the first-scaler request to 4336x2877, the camera records clean 3840x2560 files, cropped about 1.12x).

There is no preview-key routine in this kit: the FX2's own De-Squeeze Display (Off, 1.3x, 2.0x on 1.01) is kept, and S16 sets its ratios
for the 3:2 picture.

The closing session (apply and screen): one read-only dump taken with the switch on MOVIE, so that the first FX2 results show the sensor
in its full-height mode and the rear panel's type. Nothing is written in that session.

Rules it keeps:
- It starts only if the newest saved read-only check of this kit says VERDICT READY.
- It stops at the first step that does not end in DONE or NOTHING TO DO, and says what state that leaves.
- Each step is one pinned library; the runner (fx2_run.py) refuses any other bytes.
Nothing is written to a firmware file or to the camera's settings. What is written lives in the running camera's memory. A cold
boot (battery out for 10 seconds) removes it. The power switch alone does NOT (GitHub issue 5): on the FX2 it restarts the image
processor, so the coprocessor steps (L13, L5/H5, L16, S16) are stock again, but the main processor keeps the encoder step (L19). That
mixed state must not be used for recording: take the battery out, or run the putback, then apply again. Keep the FX2 switched on from
the first step to the last.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
import ct1_common as c  # noqa: E402
import fx2_run  # noqa: E402

FIRMWARE = fx2_run.FIRMWARE
STEPS = {"apply": ("L13", "L5", "L16", "L19"), "putback": ("L20", "L17", "L6", "L14"), "screen": ("S16",), "screen-putback": ("S17",),
         "test1": ("L13", "B5"), "test2": ("L13", "L5"), "test3": ("L13", "L5", "L16"), "test4": ("L13", "L5", "L16", "L19"),
         # squeeze (2026-11-26, a tester's pull request; ran on an FX2): test 2 plus the screen step. The file is 3840x2160 holding the whole 3:2
         # sensor area squeezed 27/32 vertically, and the 3:2 rear screen shows it at its true shape. No output-size or encoder step.
         "squeeze": ("L13", "L5", "S16"),
         # fourth kit (2026-11-26): the path to a true 3840x2560 file (H5 = ogh2560_fx2_v1 in L5's place), and the fallback (F16)
         "test5": ("L13", "H5"), "test6": ("L13", "H5", "L16"), "og2560": ("L13", "H5", "L16", "L19", "S16"),
         "test7": ("L13", "L5", "F16", "L16", "L19"),
         "putback-2560": ("S17", "L20", "L17", "H6", "L14"), "putback-hold": ("L20", "L17", "F17", "L6", "L14"),
         # 2026-11-27 (GitHub issue 7): the A7 IV's real 5760x3840 state (F906; 300 Mbps on the 100M+ settings, I and P pictures only, the MP4
         # headers at 5760x3840: its open_gate_apply_57 default) on the FX2: K5 (records for a 5760x3840 first scaler), K16 (four scaler units,
         # the 0x43f output buffer, the output size), K19 (the encoder side). The screen step is the 4K one (the picture is 3:2 either way)
         "og57": ("L13", "K5", "K16", "K19", "S16"), "putback-57": ("S17", "K20", "K17", "K6", "L14"),
         # XAVC S-I 4K as well (the A7 IV's ogfilesi2560_v1 / ogfilesi57_v1, one more encoder step on top of the HS/S one; 5.7K S-I works on an
         # A7 IV at 24p, F1014): issue 7 found S-I stopping REC at once with the 4K patch, because no S-I step was in it
         "og2560si": ("L13", "H5", "L16", "L19", "I19", "S16"), "og57si": ("L13", "K5", "K16", "K19", "G19", "S16"),
         "putback-2560si": ("S17", "I20", "L20", "L17", "H6", "L14"), "putback-57si": ("S17", "G20", "K20", "K17", "K6", "L14")}
TESTS = ("test1", "test2", "test3", "test4", "squeeze", "test5", "test6", "og2560", "test7", "og57", "og2560si", "og57si")
FOURTH = {"test5": "the taller first-scaler picture (4336x2560) with the stock output size. Expected: what test 2 gives, a steady picture and squeezed 3840x2160 clips.",
          "test6": "test 5 plus the output size 3840x2560. A diagnostic step only: look at the screen, do NOT record (the encoder is still set for 2,160 rows).",
          "og2560": "the path to a true 3840x2560 file: raw write buffer, the sensor side with a 4336x2560 first scaler, output size, encoder side, rear screen. "
                    "Expected: clips of 3840x2560.",
          "test7": "the fallback: the squeeze design with one code word that keeps the first-scaler size, then output size and encoder side. Expected: clips of 3840x2560 "
                   "(2,438 rows enlarged, as on the A7 IV). Run it only if test 5 does not give a picture.",
          "og57": "5.7K: raw write buffer, the sensor side with a 5760x3840 first scaler, four scaler units with a 30.8 MB output buffer and the output size "
                  "5760x3840, the encoder side (300 Mbps on the 100M+ settings, I and P pictures only, MP4 headers 5760x3840), rear screen. Expected: "
                  "clips of 5760x3840 with real detail, as on the A7 IV (F906).",
          "og2560si": "og2560 plus XAVC S-I 4K (AVC intra 4:2:2 10-bit) at 3840x2560: one more encoder step on top of the HS/S one.",
          "og57si": "og57 plus XAVC S-I 4K at 5760x3840: one more encoder step on top of the 5.7K one."}
# fifth kit (2026-11-27): the PAL sensor-side steps (mode 0x880) that take the NTSC ones' place with --pal; test1's band design has none
PAL_STEPS = {"L5": "Q5", "L6": "Q6", "H5": "P5", "H6": "P6", "K5": "J5", "K6": "J6"}     # (5.7K: K -> J)
NO_PAL = ("test1",)
RUNNER = HERE / "fx2_run.py"
LISTER = HERE.parent / "CT1_usb_first_contact" / "ct1_stage2_service.py"
STILL = "STILL (the Still/Movie switch on STILL)"
RATE = {"NTSC": "24p (23.98p)", "PAL": "25p"}
# the 4K formats the open gate is set up for: on a PAL-set FX2 XAVC HS 4K is 50p only (GitHub issue 5), so PAL is XAVC S 4K 25p alone
FORMATS = {"NTSC": "XAVC HS 4K or XAVC S 4K", "PAL": "XAVC S 4K (on PAL the FX2's XAVC HS 4K is 50p only)"}
MOVIE_BY = {f: "MOVIE (the Still/Movie switch on MOVIE; File Format %s, %s)" % (FORMATS[f].split(" (")[0], RATE[f]) for f in RATE}
MOVIE = MOVIE_BY["NTSC"]
# test results on FX2s (GitHub issues 1 and 5), printed with each target in place of the earlier "not yet run"
STATUS = {"test5": "Ran on an FX2: a steady picture (GitHub issue 5).",
          "test6": "Ran on an FX2: a steady picture, but a recording froze the camera (GitHub issue 5).",
          "og2560": "WORKS on FX2s set to NTSC (23.98p) and to PAL (25p): 3840x2560 files (GitHub issue 5).",
          "test7": "Not run on an FX2 (not needed: og2560 works).",
          "og57": "NOT YET RUN ON AN FX2: the A7 IV's 5.7K steps (they record 5760x3840 there), checked against the FX2's own code in emulation.",
          "og2560si": "og2560 works on FX2s; its S-I step is NOT YET RUN on an FX2 (on the A7 IV only the 5.7K S-I step ran: it works, F1014).",
          "og57si": "NOT YET RUN ON AN FX2 (5.7K S-I works on an A7 IV at 24p, F1014)."}
# what the 5.7K and S-I targets record, by family (on a PAL FX2, XAVC HS 4K is 50p only)
TARGET_FORMATS = {"og57": {"NTSC": "XAVC HS 4K or XAVC S 4K", "PAL": "XAVC S 4K"},
                  "og2560si": {"NTSC": "XAVC HS 4K, XAVC S 4K or XAVC S-I 4K", "PAL": "XAVC S 4K or XAVC S-I 4K"},
                  "og57si": {"NTSC": "XAVC HS 4K, XAVC S 4K or XAVC S-I 4K", "PAL": "XAVC S 4K or XAVC S-I 4K"}}


def last_family():
    """NTSC or PAL as the newest saved check or dump of this kit reads it from the camera's stored records (fx2read_v5's check, or any
    dump), or None when that result does not say (older helpers' checks) or there is none."""
    for folder, man in sessions():
        res = man.get("results", {})
        f = (res.get("ct6", {}).get("result") or {}).get("s3")
        if res.get("which") in ("check", "dump") and f:
            fam = fx2_run.camera_state(f)["family"].split(" ")[0]
            return (folder.name, fam) if fam in ("NTSC", "PAL") else None
    return None


def choose_family(a, live):
    """The family the sensor-side steps are taken for: --ntsc / --pal, else the newest check's reading, else asked (live) or NTSC (dry run)."""
    if a.ntsc and a.pal:
        raise SystemExit("--ntsc and --pal together. Nothing was sent.")
    known = last_family()
    given = "NTSC" if a.ntsc else "PAL" if a.pal else None
    if given and known and known[1] != given:
        raise SystemExit("--%s was given, but the newest check (%s) reads this camera as %s. Set the camera's NTSC/PAL Selector, run check_readonly "
                         "again, then apply. Nothing was sent." % (given.lower(), known[0], known[1]))
    if given or known:
        return given or known[1]
    if not live:
        say("(NTSC or PAL: not known from the saved checks; the dry run shows the NTSC steps. Add --pal for the PAL steps.)")
        return "NTSC"
    say("Is the camera set to NTSC or PAL? (the menu's NTSC/PAL Selector; PAL: 25p / 50p, NTSC: 23.98p / 29.97p / 59.94p)")
    ans = input("Type NTSC or PAL: ").strip().upper()
    if ans not in ("NTSC", "PAL"):
        raise SystemExit("Neither NTSC nor PAL. Nothing was sent.")
    return ans


def say(text=""):
    print(text, flush=True)


def sessions():
    """Saved sessions of this kit, newest first: (folder, manifest)."""
    root = c.PRIVATE_ROOT
    out = []
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
            try:
                out.append((folder, json.loads((folder / "manifest.json").read_text(encoding="utf8"))))
            except (OSError, ValueError):
                continue
    return out


def last_check():
    """The newest saved read-only check of this kit that fetched a result: (folder name, ready?) or None. A check that stopped before the
    camera answered (no driver yet, no camera seen, an old result on the RAM disk) says nothing and is skipped. A check made with another
    kit (the FX3's fx3read, the A7S III's s3read, the ZV-E1's zvread) does not count: its header is not this helper's."""
    for folder, man in sessions():
        res = man.get("results", {})
        f = (res.get("ct6", {}).get("result") or {}).get("s3")
        if res.get("which") in ("check", "dump") and f:       # a dump makes every check the check makes, and gives the same verdict
            current = any(v in f.get("header", "") for v in ("fx2read_v1 ", "fx2read_v2 ", "fx2read_v3 ", "fx2read_v4 ", "fx2read_v5 ")) and "ILME-FX2 1.01" in f.get("header", "")
            return folder.name, current and bool(f.get("ready")) and not f.get("identity_differs")
    return None


def last_result_sha():
    """The SHA-256 of the result the newest session fetched: the runner deletes a result left on the RAM disk only if it has this hash."""
    for _, man in sessions():
        try:
            return man["results"]["ct6"]["result"]["sha256"]
        except (KeyError, TypeError):
            continue
    return None


def usb_state():
    r = subprocess.run([sys.executable, "-I", "-B", str(LISTER), "--list"], capture_output=True, text=True, encoding="utf8", errors="replace", cwd=str(LISTER.parent))
    import re
    m = re.search(r"libusb sees: (\d+) Sony mass-storage device\(s\).*?, (\d+) Sony service device\(s\)", r.stdout)
    if not m:
        return "other"
    return "drive" if int(m.group(1)) == 1 and int(m.group(2)) == 0 else "service" if int(m.group(2)) else "other"


def wait_for_drive(first, timeout=600):
    asked, end = False, time.time() + timeout
    while usb_state() != "drive":
        if not asked:
            say()
            if first:
                say("The camera is not showing as a USB drive. Turn it on with the switch on %s, connect USB (USB Connection Mode: Mass Storage)." % STILL)
            else:
                say(">>> Unplug the USB cable from the camera and plug it in again.")
                say(">>> Do NOT power the camera off or pull the battery: that would leave the steps half done.")
            say("Waiting for the camera (Ctrl+C to stop) ...")
            asked = True
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def wait_for_replug(timeout=900, settle=6, gone=3):
    """Wait until the camera has been unplugged and shows up as a USB drive again. False on timeout.
    After a session the camera comes back on USB by itself: on macOS it is a drive again within seconds (GitHub issue 5, where the
    closing dump then ran before the switch was on MOVIE). That short gap is not an unplug. So: first the camera must be seen for
    `settle` seconds in a row (or be gone for 10, if it was unplugged at once), then be gone for `gone` seconds in a row, then be a drive."""
    end = time.time() + timeout
    seen = missing = 0
    while seen < settle and missing < 10:            # settle: the camera back after the session, steadily
        if time.time() > end:
            return False
        if usb_state() == "other":
            seen, missing = 0, missing + 1
        else:
            seen, missing = seen + 1, 0
        time.sleep(1)
    while missing < gone:                            # the unplug: gone for `gone` seconds in a row
        if time.time() > end:
            return False
        missing = missing + 1 if usb_state() == "other" else 0
        time.sleep(1)
    while usb_state() != "drive":                    # the replug
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def movie_session(test=None, family="NTSC"):
    """The closing read-only session, taken in movie mode: it shows the sensor in the open-gate mode and the panel type."""
    say()
    say("=" * 78)
    say("One more session, and it only READS: it records the sensor's state in Movie, the memory manager's state and the rear panel's type.")
    say(">>> 1. Unplug the USB cable.")
    say(">>> 2. Set %s." % MOVIE)
    if test:
        say("       Watch the rear screen for ten seconds. Write down: a picture? purple flashing? does the camera switch itself off and on?")
        say("       If there is a steady picture: press REC, record about five seconds, press REC again.")
        say("       If the camera restarts by itself: do NOT pull the battery. Wait until it is on again, leave the switch on MOVIE.")
    else:
        say("       Look at the rear screen for five seconds and remember what it shows (the whole 3:2 picture? anything wrong?).")
    say(">>> 3. Plug the USB cable in again, still on MOVIE (after a restart too; choose Mass Storage if the camera asks).")
    say(">>> Do NOT switch the camera off: that may remove the patch.")
    say("Waiting for the unplug and the replug (Ctrl+C to stop; the patch stays applied either way) ...")
    if not wait_for_replug():
        say("The camera did not come back as a USB drive. The steps are applied all the same.")
        return
    # the replug is seen; the switch position is not, so ask (issue 5: a dump taken on STILL shows nothing of the movie state)
    if input("Is the switch on MOVIE now? Press Enter to take the read-only dump, or type SKIP: ").strip().upper() == "SKIP":
        say("No dump taken. The steps are applied. Later, on MOVIE: run dump_info.")
        return
    cmd = [sys.executable, "-I", "-B", str(RUNNER), "dump", "--go", "--firmware-shown", FIRMWARE]
    clear = last_result_sha()
    if clear:
        cmd += ["--clear-result", clear]
    rc = subprocess.run(cmd).returncode
    which, f = step_outcome()
    say()
    if rc or which != "dump" or not f:
        say("The read-only session did not finish. The steps are applied all the same.")
        return
    decoded = f.get("decoded") or {}
    column = (decoded.get("sensor_registers") or {}).get("closest_column")
    if column != fx2_run.FULL_HEIGHT_COLUMN:         # the open-gate 4K mode reads the sensor with register column 5 (as on the A7 IV), NTSC and PAL
        say("NOTE: the dump did not find the sensor in its full-height 4K mode (register column %s, not %d): the camera was probably still on" % (column, fx2_run.FULL_HEIGHT_COLUMN))
        say("      STILL, or not at 4K %s. The steps are applied all the same. Set MOVIE (%s), replug, and run dump_info." % (RATE[family], FORMATS[family].split(" (")[0]))
    panel = (decoded.get("display") or {}).get("panel_types")
    if panel:
        say("The rear panel reports type %d (%s). Please send this folder: it settles the FX2's panel shape." % (panel["rear_0x19d98cc"], panel["rear_aspect"]))
    say(">>> Unplug USB now.")


def step_outcome():
    for _, man in sessions():
        f = man.get("results", {}).get("ct6", {}).get("result", {}).get("s3")
        return (man.get("results", {}).get("which"), f) if f else (None, None)
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=sorted(STEPS))
    ap.add_argument("--dry-run", action="store_true", help="show the steps and what each would send; nothing is sent")
    ap.add_argument("--no-screen", action="store_true", help="with apply or putback: only the four open-gate steps, without the screen step")
    ap.add_argument("--no-movie-session", action="store_true", help="with apply or screen: leave out the closing read-only session in movie mode")
    ap.add_argument("--no-meta", action="store_true", help="with apply, og2560, og57 and the S-I forms: the encoder step without the MP4 header size (N19 / M19); the headers keep saying 3840x2160")
    ap.add_argument("--ntsc", action="store_true", help="the camera is set to NTSC (23.98p): the sensor-side steps L5 / H5")
    ap.add_argument("--pal", action="store_true", help="the camera is set to PAL (25p): the sensor-side steps Q5 / P5 / J5 (mode 0x880)")
    a = ap.parse_args()
    steps = STEPS[a.what]
    family = "NTSC"
    if any(k in PAL_STEPS for k in steps):
        if not a.dry_run and a.what in ("apply", "screen") + TESTS:
            chk = last_check()                       # the READY rule comes before any question (the NTSC/PAL one below included)
            if chk is None or not chk[1]:
                raise SystemExit("The newest saved read-only check of this kit %s. Run check_readonly first and get VERDICT READY. Nothing was sent."
                                 % ("does not exist" if chk is None else "(%s) does not say READY" % chk[0]))
        family = choose_family(a, not a.dry_run)
        if family == "PAL":
            steps = tuple(PAL_STEPS.get(k, k) for k in steps)
    elif a.pal and a.what in NO_PAL:
        raise SystemExit("%s has no PAL build (its band design is for mode 0x8c0, NTSC only). Nothing was sent." % a.what)
    global MOVIE
    MOVIE = MOVIE_BY[family]
    if a.no_screen and a.what not in ("apply", "putback"):
        raise SystemExit("--no-screen goes with apply or putback. Nothing was sent.")
    if a.no_meta and a.what not in ("apply", "og2560", "og57", "og2560si", "og57si"):
        raise SystemExit("--no-meta goes with apply, og2560, og57 and their S-I forms (L20 / K20 put back either encoder step). Nothing was sent.")
    if a.no_meta:                                    # the encoder step without the MP4 header size: N19 for 4K, M19 for 5.7K
        steps = tuple({"L19": "N19", "K19": "M19"}.get(k, k) for k in steps)
    with_screen = not a.no_screen
    if a.what in ("apply", "putback") and with_screen:
        steps = steps + STEPS["screen"] if a.what == "apply" else STEPS["screen-putback"] + steps
    applying = a.what in ("apply", "screen") + TESTS
    closing = a.what in ("apply", "screen") + TESTS
    for k in steps:                                  # every library must be the pinned one before anything starts
        name, sha, _ = fx2_run.WRITE_STEPS[k]
        p = fx2_run.S3 / name
        if not p.is_file() or c.sha256(p.read_bytes()) != sha:
            raise SystemExit("%s is missing or is not the pinned build. Nothing was sent." % name)
    say("FX2 1.01, %s%s: %d steps" % (a.what, " (PAL: mode 0x880, 25p)" if family == "PAL" else "", len(steps)))
    for n, k in enumerate(steps, 1):
        say("  %d. %s  %s  (library %s...)" % (n, k, fx2_run.WRITE_STEPS[k][2], fx2_run.WRITE_STEPS[k][1][:16]))
    if closing and not a.no_movie_session:
        say("  then one read-only session (dump) on MOVIE: the sensor's state and the panel type for the first FX2 results. Nothing is written in it.")
    if a.dry_run:
        for k in steps:
            say()
            say("--- %s, what the session would send:" % k)
            r = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), k, "--dry-run"], capture_output=True, text=True, encoding="utf8", errors="replace")
            say(r.stdout.rstrip() or r.stderr.rstrip())
        say()
        say("Dry run only: nothing was sent to any device.")
        return
    chk = last_check()
    if applying and (chk is None or not chk[1]):
        raise SystemExit("The newest saved read-only check of this kit %s. Run check_readonly first and get VERDICT READY. Nothing was sent."
                         % ("does not exist" if chk is None else "(%s) does not say READY" % chk[0]))
    say()
    say("This WRITES into the running camera's memory (not its firmware, not its settings).")
    if a.what in FOURTH:
        say("This is %s of the fourth kit (%s)." % (a.what, " + ".join(steps)))
        say("  %s" % FOURTH[a.what])
        if a.what in ("og57", "og57si"):
            say("  Why it should run: the FX2 hands its second scaler at least the output size; K5's records deliver 5760x3840 and K16's output is")
            say("  5760x3840, so the two agree (emulated, NTSC and PAL). The 27.6 MB output picture gets id 0x43f, which K16 makes a 30.8 MB unit.")
            say("  300 Mbps on the 100M and higher record settings: use a V90 SD card or CFexpress Type A. The lower settings keep their bit rate.")
        else:
            say("  Why: with the output size 3840x2560 the FX2 hands its second scaler a first-scaler size of 4336x2560, and the earlier sensor step (L5)")
            say("  delivers 4336x2438: that was the crash of L13 + L5 + L16. %s" % ("H5 delivers 4336x2560." if "H5" in steps else "F16 keeps the size the records give."))
        say("  %s A restart is possible and harmless (the patch is gone after it). Each step writes nothing unless its" % STATUS[a.what])
        say("  bytes are exactly the stock bytes.")
        fmts = TARGET_FORMATS.get(a.what, {}).get(family) or FORMATS[family].split(" (")[0]
        say("  Camera settings: APS-C/Super 35 Off, S&Q off, File Format %s, %s. SteadyShot Off, Active and Dynamic Active" % (fmts, RATE[family]))
        say("  and Proxy Recording all work with og2560 (issue 5); for a first run keep SteadyShot and Proxy off%s." % (" (with 5.7K: SteadyShot Off)" if "57" in a.what else ""))
        if a.what == "test6":
            say("  TEST 6 IS A DIAGNOSTIC STEP ONLY: look at the screen, but do NOT press REC. The encoder is still set for 2,160 rows; on an FX2 a recording")
            say("  in this state froze the camera until the battery was pulled (GitHub issue 5). For clips, use og2560.")
        if family == "PAL":
            say("  PAL: the sensor-side step is %s, made for mode 0x880 (25p); it works on an FX2 set to PAL (issue 5)." % next(k for k in steps if k in PAL_STEPS.values()))
    elif a.what in TESTS:
        say("This is %s of the diagnostic ladder. On the first FX2 test the whole apply worked, but MOVIE ended in a forced" % a.what)
        say("  exception and a restart. This test applies only %s, so that the result says which part the FX2 does not take." % " + ".join(steps))
        say("  A restart is possible and harmless (the patch is gone after it). Each step writes nothing unless its bytes are exactly the stock bytes.")
        if a.what == "squeeze":
            say("  (squeeze works on FX2s, NTSC with L5 and PAL with Q5, GitHub issues 1 and 5.)")
    elif applying:
        say("On the FX2 this state CRASHES on MOVIE entry (2026-11-25 and 2026-11-26: a forced exception and a restart to stock). The first failing")
        say("  step is L16 after L5. Use open_gate_squeezed (works) or the fourth kit's open_gate_3840x2560_test instead.")
        say("  Each step writes nothing unless its bytes are exactly the FX2 1.01 stock bytes.")
    else:
        say("It has to follow an apply of this kit.")
    say("A cold boot (battery out for 10 seconds) returns the camera to stock. The power switch alone does NOT: it puts back the image processor's")
    say("steps but keeps the encoder step, a mixed state not to record in. So KEEP THE CAMERA SWITCHED ON from now until the script says it is finished.")
    if a.what == "apply" or a.what in TESTS:
        say("Before you go on: the switch on %s, a charged battery," % STILL)
        say("and a camera that was cold booted and has not been on MOVIE or S&Q since. (If it starts on MOVIE: set the switch to STILL,")
        say("pull the battery for 10 seconds, put it back and switch on.) Step L13 changes the memory manager and needs that state.")
        say("(If the open-gate state is already applied in this power-on, its steps will say NOTHING TO DO: that is fine.)")
    else:
        say("Before you go on: a charged battery, and the switch on %s." % STILL)
    if sys.platform == "darwin":
        say("On a Mac: quit Lightroom, Photos and Image Capture first. They take hold of the camera's card (Lightroom froze an FX2 on 'Accessing').")
    if input("Firmware version in the camera's menu: ").strip() != FIRMWARE:
        raise SystemExit("Not %s. Nothing was sent." % FIRMWARE)
    if input("Type YES to write to the camera's memory: ").strip() != "YES":
        raise SystemExit("Not confirmed. Nothing was sent.")
    for n, k in enumerate(steps, 1):
        if not wait_for_drive(n == 1):
            raise SystemExit("The camera did not show up as a USB drive. Stopped before step %d (%s)." % (n, k))
        say()
        say("=" * 78)
        say("Step %d of %d: %s, %s" % (n, len(steps), k, fx2_run.WRITE_STEPS[k][2]))
        cmd = [sys.executable, "-I", "-B", str(RUNNER), k, "--go", "--writes-memory", "--firmware-shown", FIRMWARE]
        clear = last_result_sha()
        if clear:
            cmd += ["--clear-result", clear]
        rc = subprocess.run(cmd).returncode
        which, f = step_outcome()
        if rc or which != k or not f or not f.get("ok"):
            say()
            say("STOPPED at step %d (%s): %s" % (n, k, "the session did not finish" if rc or which != k or not f else "outcome " + f["outcome"]))
            say("Steps before it are %s. To be sure of the camera's state: cold boot it (battery out for 10 seconds)." % ("applied" if applying else "put back"))
            if k == "L13" and f and "nothing is written" in " ".join(f.get("problem_lines", []) + [str(f.get("outcome_line"))]):
                say("L13 refuses while the movie memory is still laid out the stock way: cold boot with the switch on STILL, then apply again.")
            say("Please send the newest folders in camera_private.")
            raise SystemExit(1)
    say()
    say("All %d steps passed (%s)." % (len(steps), a.what))
    if a.what == "apply":
        if a.no_meta:
            say("The files' MP4 headers say 3840x2160 (--no-meta): editors may open them squeezed; a remux to 3840x2560 fixes that.")
        else:
            say("The files' MP4 headers (tkhd, stsd, Sony's PROF) now say 3840x2560: editors should open them at 3:2 without a remux.")
            say("  Sony's XML (in the file and the sidecar) still says 3840x2160, 16:9.")
        say("In-camera playback: the 3840x2560 clips of og2560 played on an FX2 (GitHub issue 5). If a clip says 'Unable to display', do NOT try")
        say("  again (on an FX3 a retry froze the camera); check the clips on a computer and report it.")
    if "S16" in steps:
        say("The screen step: on MOVIE the 3:2 rear screen should now be filled with the whole picture at its true shape. A circle should look round.")
        say("  The viewfinder (a 4:3 panel) keeps showing the picture squeezed, as on the A7 IV.")
        say("  De-Squeeze Display (in the menu's Display Option) now de-squeezes the 3:2 picture: 1.3x shows 1.95:1, 2.0x 3:1 (the whole frame;")
        say("  the stock centre crop is off). The file does not change. While it is applied every 16:9 picture is shown stretched to 3:2")
        say("  (other movie formats look wrong on the rear screen). Please report: the screen with De-Squeeze Display Off, 1.3x and 2.0x,")
        say("  and whether the focus and tracking frames sit on the subject.")
    if a.what in TESTS:
        if a.no_movie_session:
            say(">>> Unplug USB, set %s, then run dump_info on MOVIE (after a restart too)." % MOVIE)
        else:
            movie_session(a.what, family)
        say()
        say("Please send the newest folders in camera_private, and what the screen did on MOVIE: a picture (which shape?), purple flashing,")
        say("  a restart? If it recorded: the clip's properties (size, frame rate), or the clip. To return to stock: battery out for 10 seconds.")
        if a.what in ("og2560", "test7", "og57", "og2560si", "og57si"):
            say("  For a clip of this test: the size MediaInfo shows (%s expected), whether it plays on a computer, and whether a recording"
                % ("5760x3840" if "57" in a.what else "3840x2560"))
            say("  stops by itself.%s" % (" PAL: the frame rate MediaInfo shows (25 expected)." if family == "PAL" else ""))
        say("  Do not use the power switch to undo it: it keeps the encoder step (L19) and leaves a mixed state. Battery out, or the putback.")
        say("  Do not change the frame rate or the file format while it is applied: the camera restarts by itself and is stock again (harmless).")
        if "57" in a.what:
            say("  5.7K clips do not play back in the camera (on the A7 IV they never did): check them on a computer, and do not retry playback.")
        say("  Before the next test: battery out for 10 seconds, switch on with the switch on STILL.")
        return
    if closing:
        if a.no_movie_session:
            say(">>> Unplug USB, then set %s." % MOVIE)
        else:
            movie_session(family=family)
        say()
        say("Use only %s at %s while it is applied: other 4K formats and frame rates are not set up and fail." % (FORMATS[family], RATE[family]))
        say("Changing the frame rate while it is applied restarts the camera, back to stock (GitHub issue 5): harmless, but the patch is gone.")
        say("If the camera stops or restarts: do NOT pull the battery yet. Set the switch to STILL, replug USB and run dump_info, then send camera_private.")
        say("To return to stock: battery out for 10 seconds. Do not use the power switch for that: it leaves the encoder step applied.")


if __name__ == "__main__":
    main()
