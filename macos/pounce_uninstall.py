"""FX2: pounce - send W41 the instant the camera appears (LOCAL, 2026-11-28).

For an operator who controls the timing: unplug the camera, let it settle, plug it back in, and this fires the moment the device
appears. Everything that does not need the camera is done BEFORE the wait, so the only work left on appearance is the USB
session itself.

What changes from fast_uninstall.py, all of it measured:
  - the library is loaded, SHA-256 verified and its guard rules built before the wait (F.use + R.rules);
  - c.use_pmca(), c.print_pnp() and the session bookkeeping happen before the wait (print_pnp shells out to ioreg - slow);
  - the poll is a bare libusb find at 50 ms, not the kit's libusb_devices() which builds two contexts each call;
  - the 3 s post-step sleep, the known-answer read and the result fetch are gone (see fast_uninstall.py for the measurements).

It still uses the kit's own Guard on the packet (one write, the pinned W41 library only) and still sends the stop request.

  sudo ./.venv/bin/python pounce_uninstall.py                wait up to 5 minutes
  sudo ./.venv/bin/python pounce_uninstall.py --wait 1800    up to 30 minutes
  sudo ./.venv/bin/python pounce_uninstall.py --armed-only   just wait and report, send nothing

Sequence that works best (the operator's idea): unplug, let the camera settle with the screen off, then plug in - and this fires
on the appearance, before whatever kills the camera has time to act.
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

STEP = "W41"
POLL = 0.05          # 50 ms


def say(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def find_camera():
    """(what, handle) for the one Sony camera present IN A MODE THE KIT CAN USE, or (None, None).

    Only mass storage (interface class 8) and service mode (class 255) count. PC Remote / HID (class 3, e.g. 054c:0d68) does NOT:
    service.connect() builds its device lists with MscContext and VendorSpecificContext, so a HID-only appearance makes it raise
    "libusb sees 0 Sony mass-storage and 0 Sony service devices" - the window is spent for nothing. That is exactly what happened on
    the first real run (2026-11-28 11:56Z: pounce fired on 0d68, connect() refused, nothing was sent).
    """
    import usb.core
    ds = list(usb.core.find(find_all=True, idVendor=0x054C))
    for d in ds:
        try:
            cls = {i.bInterfaceClass for c in d for i in c}
        except Exception:
            continue                                   # enumerated but not readable yet: not usable
        if 8 in cls:
            return "mass storage (0f47)", d
        if 255 in cls:
            return "service mode (%04x)" % d.idProduct, d
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=300, help="seconds to wait (default 300)")
    ap.add_argument("--armed-only", action="store_true", help="report appearances, send nothing")
    a = ap.parse_args()

    # ---- everything that does not need the camera, BEFORE the wait ----
    import ct1_common as c
    import fx2_run as F
    import ct1_stage2_service as service
    import ct6_level1_run as R

    lib = F.use(STEP)
    rules = R.rules(lib)
    c.use_pmca()
    say("armed: %s pinned (%d bytes, %s), guard rules built, pmca ready"
        % (STEP, len(lib), F.PINS[STEP][1][:16]))
    say("waiting for the camera (poll %d ms, up to %d s) - unplug, settle, plug in" % (int(POLL * 1000), a.wait))

    deadline = time.time() + a.wait
    seen = None
    ignored = None
    while True:
        what, handle = find_camera()
        if what:
            if what != seen:
                say("APPEARED IN A USABLE MODE: %s" % what)
                seen = what
            break
        # report modes the kit cannot use, once each, so the log shows what the camera is doing
        import usb.core
        try:
            others = ["%04x/class%s" % (d.idProduct, "".join(str(i.bInterfaceClass) for c in d for i in c))
                      for d in usb.core.find(find_all=True, idVendor=0x054C)]
        except Exception:
            others = []
        tag = " ".join(others) if others else None
        if tag != ignored:
            ignored = tag
            if tag:
                say("seen but not usable by the kit: %s (need class 8 or 255)" % tag)
            else:
                say("nothing from Sony")
        if time.time() > deadline:
            say("no usable appearance within %d s; nothing was sent" % a.wait)
            return 2
        time.sleep(POLL)

    if a.armed_only:
        say("--armed-only: not sending")
        return 0

    t0 = time.time()
    session = c.Session("pounce_uninstall", test="CT6")
    with session:
        session.results.update(firmware_shown_on_camera="1.01", which="pounce_uninstall", plan=[STEP],
                               libraries={STEP: F.PINS[STEP][1]})
        try:
            inner = service.connect(session)           # mode switch if needed + auth
        except Exception as exc:
            say("connect failed after %.2f s: %s: %s" % (time.time() - t0, type(exc).__name__, exc))
            return 3
        say("connected in %.2f s" % (time.time() - t0))

        def body(cam):
            out = session.results["ct6"] = {"library_bytes": len(lib), "library_sha256": R.LIB_SHA256,
                                            "library_sent": False, "pounce": True}
            R.select(cam, R.LIB_PATH)
            out["library_sent"] = True
            t = time.time()
            status, _ = R.command(cam, "SET_FILE2", b"\x00\xff\x00" + lib)
            out["write_status"] = status
            say("write and load: status %s (%.2f s from appearance)" % (R.text(status), time.time() - t0))
            R.remove(session, cam, out)
            say("DONE in %.2f s: /etc/ld.so.preload removed if the camera accepted the write" % (time.time() - t0))

        try:
            R.service_session(session, inner, body, lib)
        except Exception as exc:
            say("stopped: %s: %s" % (type(exc).__name__, exc))
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
