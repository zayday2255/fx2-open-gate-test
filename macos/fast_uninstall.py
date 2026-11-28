"""FX2: the fastest possible uninstall - delete /etc/ld.so.preload - for a camera whose USB window is short (LOCAL, 2026-11-28).

WHY THIS EXISTS
The kit's loader_uninstall does more than the job needs: it reads DeviceInfo.xml (a 16 KB known-answer check), reads the library
file, reads the result file, reads the busy flag, then uploads a 10.6 KB library, removes it, reads the result, and finally sleeps 3
seconds to print the USB state. Measured, that is roughly 5 s from "camera appears" to "hook deleted".

The camera that this is for appears for as little as 2-3 s at a time (measured in service_watch.log: durations of 79, 3, 3, 3, ...
seconds). So the post-step sleep and the reads that do not affect the outcome are pure loss.

WHAT IT KEEPS (nothing here is a safety check that can be dropped):
  - the same pinned library (SHA-256 verified against fx2_run.PINS before a byte is sent);
  - the same per-library guard on the packet (R.GUARDS, one write, that library only);
  - the camera's own guard: the library writes nothing unless every site it changes holds its stock value. W41 only unlinks
    /etc/ld.so.preload, /etc/fx2boot and the earlier research builds' files - there is nothing to guard wrong, and it needs none of
    the loader's files to be intact. That is why it is the way back.
  - the stop request is still sent.

WHAT IT DROPS: known_answer(), the pre-flight reads of the library/result/busy files, the result fetch, and the 3 s sleep.

  sudo ./.venv/bin/python fast_uninstall.py            (needs the camera in mass storage or service mode)
  sudo ./.venv/bin/python fast_uninstall.py --wait 600 wait up to 10 minutes for the camera to appear

It prints one line per phase so the log shows exactly where a short window ran out.
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOOLS = ROOT / "windows/tools/camera_tests/CT6_memory_read_check"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(TOOLS.parent.parent / "third_party/sony-pmca-re"))

import ct1_common as c          # noqa: E402
import fx2_run as F             # noqa: E402
import ct1_stage2_service as service   # noqa: E402
import ct6_level1_run as R      # noqa: E402

STEP = "W41"                    # the uninstall: removes /etc/ld.so.preload first, then /etc/fx2boot


def say(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def fast_body(session, camera, lib):
    """The minimum that removes the loader. No known-answer read, no pre-flight file reads, no result fetch."""
    out = session.results["ct6"] = {"library_bytes": len(lib), "library_sha256": R.LIB_SHA256, "library_sent": False, "fast": True}
    say("selecting the library path")
    R.select(camera, R.LIB_PATH)                       # a failure here stops with nothing written
    say("sending %d bytes" % len(lib))
    out["library_sent"] = True
    try:
        status, _ = R.command(camera, "SET_FILE2", b"\x00\xff\x00" + lib)
    except Exception as exc:
        out["library_sent"] = False
        say("the write was refused: %s: %s" % (type(exc).__name__, exc))
        raise
    out["write_status"] = status
    say("write and load: status %s" % R.text(status))
    R.remove(session, camera, out)                     # the stop request; the library is taken off the service partition
    say("library removed, stop request sent")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait for the camera (default 120)")
    a = ap.parse_args()

    lib = F.use(STEP)                                   # the pinned build, or it stops here
    say("uninstall library %s (%d bytes, %s)" % (STEP, len(lib), F.PINS[STEP][1][:16]))

    deadline = time.time() + a.wait
    while True:
        try:
            msc, senser = service.libusb_devices()
            if msc or senser:
                say("camera present: %d mass-storage, %d service" % (len(msc), len(senser)))
                break
        except Exception as exc:
            say("waiting (usb error: %s)" % type(exc).__name__)
        if time.time() > deadline:
            say("the camera did not appear within %d s; nothing was sent" % a.wait)
            return 2
        time.sleep(0.25)

    t0 = time.time()
    with c.Session("fast_uninstall", test="CT6") as session:
        session.results.update(firmware_shown_on_camera="1.01", which="fast_uninstall", plan=[STEP],
                               libraries={STEP: F.PINS[STEP][1]})
        inner = service.connect(session)               # mode switch if needed + auth
        say("connected in %.1f s" % (time.time() - t0))
        try:
            R.service_session(session, inner, lambda cam: fast_body(session, cam, lib), lib)
        finally:
            say("done in %.1f s total" % (time.time() - t0))
            out = session.results.get("ct6", {})
            say("library sent: %s" % out.get("library_sent"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
