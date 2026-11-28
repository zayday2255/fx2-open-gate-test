"""CT1 stages 2 and 3: service mode, settings backup, two file reads. Reads only.

Camera: USB Connection Mode = Mass Storage. The camera's USB device needs the
libusb-win32 driver (Zadig), first in mass-storage mode, then again once it
has switched to service mode. So a first live run normally ends with
"install the driver for the service device and run again": that is expected.

  python -I -B ct1_stage2_service.py --dry-run     run against the simulated camera, list what is sent
  python -I -B ct1_stage2_service.py --list        show which Sony devices libusb can see; sends nothing
  python -I -B ct1_stage2_service.py --go --firmware-shown 6.02 [--no-probes]

Order in the service session: READ_HASP, backup read, backup saved and parsed,
then (unless --no-probes) DeviceInfo.xml and /proc/cmdline, then the stop request.
Every packet passes the guards in ct1_common. Nothing is retried.
"""
import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct1_common as c
import ct1_compare

SENSER_PIDS = (0x02A9, 0x0336)


# ------------------------------------------------------------ the session

def phase_a(session, inner):
    """Mass-storage device: start request, then PMCA-RE's first exchange. The camera then re-enumerates."""
    from pmca.usb.sony import SonySenserAuthDevice
    driver = c.GuardedDriver(inner, session, "msc")
    auth = SonySenserAuthDevice(driver)
    session.say("Switching to service mode")
    auth.start()
    try:
        auth.authenticate()
    except Exception as exc:
        # The camera may drop off the bus part-way through this exchange. PMCA-RE's own
        # instruction is to run again once the service device has appeared; we just go
        # on to look for that device. Nothing is sent again here.
        session.log("phase_a_exchange_ended", error="%s: %s" % (type(exc).__name__, exc))
        session.say("First exchange ended early (%s); looking for the service device" % type(exc).__name__)
    session.results["auth_msc"] = ct1_compare.auth_summary(session.events, "msc")


def phase_b(session, inner, probes, pred):
    """Service device: authenticate, CT1's guarded reads, stop request (always)."""
    service_session(session, inner, lambda camera: reads(session, camera, probes, pred))


def service_session(session, inner, body, rules=None):
    """Authenticate on the service device, run body(camera) under the guard, always send the stop request."""
    from pmca.usb.sony import SonySenserAuthDevice, SonySenserCamera, SonySenserDevice
    driver = c.GuardedDriver(inner, session, "senser")
    session.results["service_usb_id"] = "%04x:%04x" % driver.getId()
    auth = SonySenserAuthDevice(driver)
    session.say("Authenticating")
    auth.start()
    try:
        try:
            auth.authenticate()
        finally:
            session.results["auth_service"] = ct1_compare.auth_summary(session.events, "senser")
        device = SonySenserDevice(driver)
        c.ServiceGuard(device, session, rules)
        body(SonySenserCamera(device))
    finally:
        auth.stop()
        session.say("Stop request sent")


def reads(session, camera, probes, pred):
    hasp = camera.readHasp()
    session.save_bytes("hasp.bin", hasp)

    session.say("Reading the settings backup from memory")
    backup = camera.getBackupPresetData(True)
    if not backup:
        raise c.StopTest("the camera returned an empty backup")
    digest = session.save_bytes("backup_live.bin", backup)
    session.say("Backup saved: %d bytes, SHA-256 %s" % (len(backup), digest))
    outcomes, facts = ct1_compare.evaluate_backup(backup, pred)
    session.results["backup"] = {k: facts.get(k) for k in ("bytes", "sha256", "banks", "region", "version", "properties")}
    session.results["backup_outcomes"] = outcomes
    ct1_compare.print_outcomes(outcomes)
    if "banks" not in facts:
        raise c.StopTest("the backup does not parse as BK4; the file probes are skipped")
    if not probes:
        return

    for index, path in enumerate(c.PROBE_PATHS):
        key = "probe%d" % (index + 1)
        shown = "/" + path.decode().replace("../", "")
        session.say("Reading %s" % shown)
        result = session.results[key] = {"path": shown}
        try:
            camera._sendAdjustControlPacket(0x1001, 0x400F, b"\x00" + path)
            answer = camera._sendAdjustControlPacket(0x1001, 0x4011, b"\x00\xff\x00")
        except c.GuardRefusal:
            raise
        except Exception as exc:
            result["error"] = "%s: %s" % (type(exc).__name__, exc)
            session.say("  no answer: %s" % result["error"])
            if index == 0:
                raise c.StopTest("the known-answer read failed; stopping before the second read")
            break                                     # the last read: its failure is the result
        status = struct.unpack_from("<I", answer)[0] if len(answer) >= 4 else None
        payload = answer[4:]
        result.update(status=status, bytes=len(payload), sha256=c.sha256(payload), answer_bytes=len(answer))
        session.save_bytes("%s.bin" % key, payload)
        session.say("  status %s, %d bytes, SHA-256 %s" % (status, len(payload), result["sha256"]))
        if index == 0:
            want = pred["files"][shown]
            if (len(payload), result["sha256"]) != (want["bytes"], want["sha256"]):
                raise c.StopTest("DeviceInfo.xml does not match the 6.02 file; stopping before the second read")
            session.say("  matches the file in the 6.02 update")


# ------------------------------------------------------------ real USB devices

def libusb_devices():
    """(mass-storage handles, service handles) that libusb can see, Sony only."""
    import usb.core
    from pmca.usb.driver.generic import libusb
    try:
        msc = list(libusb.MscContext().listDevices(c.SONY_VID))
        vendor = list(libusb.VendorSpecificContext().listDevices(c.SONY_VID))
    except usb.core.NoBackendError:
        if sys.platform == "darwin":
            raise c.StopTest("pyusb found no libusb library. Run macos/setup.command again (it installs libusb-package)")
        raise c.StopTest("pyusb found no libusb library. The libusb-win32 driver is not installed yet: "
                         "do the Zadig step for the camera in Mass Storage mode, then run again")
    return msc, [d for d in vendor if d.idProduct in SENSER_PIDS]


def wait_for_service_device(session):
    for _ in range(10):
        time.sleep(0.5)
        try:
            _msc, senser = libusb_devices()
            if len(senser) == 1:
                return senser[0]
        except Exception:
            pass
    return None


def live(session, probes):
    pred = ct1_compare.load_predictions()
    inner = connect(session)
    try:
        phase_b(session, inner, probes, pred)
    finally:
        time.sleep(3)
        c.print_pnp(session, "after the stop request")


def connect(session):
    """Find the camera, switch it to service mode if needed, return the service device's driver."""
    c.use_pmca()
    c.print_pnp(session, "start")
    msc, senser = libusb_devices()
    try:
        session.results["libusb_backend"] = type((msc + senser)[0].handle.backend).__module__
    except Exception:
        session.results["libusb_backend"] = None
    if len(msc) + len(senser) != 1:
        hint = "Unplug other Sony USB devices" if sys.platform == "darwin" else "Check the Zadig step and unplug other Sony USB devices"
        raise c.StopTest("libusb sees %d Sony mass-storage and %d Sony service devices; exactly one camera is "
                         "needed. %s" % (len(msc), len(senser), hint))
    handle = senser[0] if senser else None
    if msc:
        from pmca.usb import MscDevice
        from pmca.usb.driver.generic import libusb
        from pmca.usb.sony import isSonyMscCamera
        inner = libusb.MscContext().openDevice(msc[0])
        if sys.platform == "darwin":
            take_over_from_macos(session, inner)
        session.log("note", text="SCSI TEST UNIT READY and INQUIRY through PMCA-RE MscDevice")
        info = first_msc_contact(session, inner, MscDevice)
        session.results["msc_usb_id"] = "%04x:%04x" % (msc[0].idVendor, msc[0].idProduct)
        session.results["msc_inquiry"] = {"manufacturer": info.manufacturer, "model": info.model}
        session.say("%s %s is a camera in mass storage mode (%s)"
                    % (info.manufacturer, info.model, session.results["msc_usb_id"]))
        if not isSonyMscCamera(info):
            raise c.StopTest("the mass-storage device does not identify as a Sony camera")
        phase_a(session, inner)
        session.say("Waiting for the camera to switch")
        handle = wait_for_service_device(session)
        rows = c.print_pnp(session, "after the switch")
        if handle is None:
            there = [r for r in rows if sys.platform == "win32" and "PID_0336" in (r.get("instance_id") or "").upper()]
            if there:
                session.results["service_device_seen_by_windows"] = c.mask_instance_id(there[0]["instance_id"])
                raise c.StopTest("EXPECTED on a first run: the camera is in service mode (054C:0336) but that "
                                 "device has no libusb driver yet. Leave the camera connected and on, install "
                                 "libusb-win32 for it with Zadig, then run this command again")
            raise c.StopTest("the camera did not come back as a service device within 5 seconds")
    from pmca.usb.driver.generic import libusb
    session.results["service_interface_class"] = 255         # it was listed by interface class 255
    session.say("Found a camera in service mode")
    return libusb.VendorSpecificContext().openDevice(handle)


def first_msc_contact(session, inner, msc_device, tries=3, pause=2.0):
    """TEST UNIT READY + INQUIRY, the first packets to the camera. On macOS the first one can time out right after the
    mass-storage driver is detached (seen on FX2s, issue 7: the run only went on after a second replug). On a timeout
    this does the USB mass-storage reset recovery (Bulk-Only Mass Storage Reset, then clear-halt on both bulk
    endpoints), waits and tries again. Both are standard mass-storage requests: nothing reaches the service side."""
    from pmca.usb.driver.generic import GenericUsbException
    for attempt in range(1, tries + 1):
        try:
            return msc_device(inner).getDeviceInfo()
        except GenericUsbException:
            if sys.platform != "darwin" or attempt == tries:
                raise
            session.log("note", text="first mass-storage command timed out (try %d of %d): reset recovery" % (attempt, tries))
            session.say("The camera did not answer the first USB command; resetting the USB link and trying again (%d of %d)"
                        % (attempt + 1, tries))
            for step in (lambda: inner.backend.classInterfaceRequestOut(0xFF, 0, 0),
                         lambda: inner.backend.clearHalt(inner.epIn[0]),
                         lambda: inner.backend.clearHalt(inner.epOut[0])):
                try:
                    step()
                except Exception as exc:         # the recovery is best effort; the retry below is the real test
                    session.log("note", text="reset recovery step failed: %r" % exc)
            time.sleep(pause)


def take_over_from_macos(session, inner):
    """macOS keeps its own mass-storage driver on the camera. libusb can talk to it only once that driver lets go,
    which macOS allows only as root. The card is unmounted first; then PMCA-RE's UsbBackend.reset() detaches the
    driver from interface 0. Nothing is sent to the camera here."""
    import os
    import usb.core
    if os.geteuid() != 0:
        raise c.StopTest("macOS holds the camera with its own mass-storage driver, and taking it over needs admin "
                         "rights. Run the launchers in the macos folder: they ask for your password")
    c.unmount_sony_disks(session)
    try:
        inner.reset()
    except usb.core.USBError as exc:
        raise c.StopTest("macOS did not let go of the camera's mass-storage driver (%s)" % exc)
    session.log("note", text="macOS mass-storage driver detached through PMCA-RE UsbBackend.reset")
    session.say("macOS let go of the camera")


# ------------------------------------------------------------ dry run

def dry_run_lines():
    """Run the real stage code and the real PMCA-RE classes against the simulated camera."""
    import contextlib
    import io
    import ct1_sim
    c.use_pmca()
    pred = ct1_compare.load_predictions()
    session = c.Session("dry_run", write=False)
    msc = ct1_sim.SimDriver("msc")
    senser = ct1_sim.SimDriver("senser", ct1_sim.default_backup(), ct1_sim.default_files())
    with contextlib.redirect_stdout(io.StringIO()):
        phase_a(session, msc)
        phase_b(session, senser, True, pred)
    if msc.unexpected or senser.unexpected:
        raise AssertionError("simulated camera saw something off the list: %r" % (msc.unexpected + senser.unexpected))
    lines, device, auth = [], None, 0

    def flush_auth():
        nonlocal auth
        if auth:
            lines.append("  %d authentication packets of 516 bytes on bulk endpoint 0 "
                         "(PMCA-RE SonySenserAuthDevice.authenticate)" % auth)
            auth = 0

    for e in session.events:
        if e.get("dev") and e["dev"] != device:
            flush_auth()
            device = e["dev"]
            lines.append("To the mass-storage device (after SCSI TEST UNIT READY and INQUIRY):" if device == "msc"
                         else "To the service device 054C:0336:")
        if e["kind"] == "usb_vendor_out":
            flush_auth()
            lines.append("  vendor request out: request %d, value %s, index %s, no data  (%s)"
                         % (e["request"], e["value"], e["index"], e["name"]))
        elif e["kind"] == "usb_out" and e["bytes"] == 516:
            auth += 1
        elif e["kind"] == "service_out":
            flush_auth()
            body = bytes.fromhex(e["hex"])
            lines.append("  service packet type 0x%02x, body %s  (%s%s)"
                         % (e["pfunc"], body.hex(" "), e["name"],
                            ": " + body[5:].decode() if e["name"] == "SET_FILE_PATH" else ""))
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--go", action="store_true")
    parser.add_argument("--firmware-shown", help="the version the camera's menu shows (must be 6.02)")
    parser.add_argument("--no-probes", action="store_true", help="backup only; skip the two file reads")
    args = parser.parse_args()

    if args.dry_run:
        print("Stage 2 and 3 would send, in this order:")
        print("\n".join(dry_run_lines()))
        return
    if args.list:
        c.use_pmca()
        session = c.Session("list", write=False)
        c.print_pnp(session, "now")
        try:
            msc, senser = libusb_devices()
        except c.StopTest as exc:
            print(exc)
            return
        print("libusb sees: %d Sony mass-storage device(s) %s, %d Sony service device(s) %s"
              % (len(msc), ["%04x:%04x" % (d.idVendor, d.idProduct) for d in msc],
                 len(senser), ["%04x:%04x" % (d.idVendor, d.idProduct) for d in senser]))
        print("Nothing was sent to any device.")
        return
    if args.firmware_shown != c.EXPECTED_FIRMWARE:
        raise SystemExit("Pass --firmware-shown with the version on the camera's menu. CT1 is prepared for "
                         "%s only; anything else stops here." % c.EXPECTED_FIRMWARE)
    with c.Session("stage2_service") as session:
        session.results["firmware_shown_on_camera"] = args.firmware_shown
        live(session, not args.no_probes)
        print("No setting was written and no file was written to the camera.")


if __name__ == "__main__":
    main()
