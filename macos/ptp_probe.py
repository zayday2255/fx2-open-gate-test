"""FX2: can the camera be told to switch to mass storage over its PC-Remote USB identity? (LOCAL, 2026-11-28)

READ-ONLY PROBE. It sends one standard PTP request (GetDeviceInfo) and nothing else. Nothing is written to the camera or to flash.

Why: the camera in a restart loop never enumerates as mass storage (054c:0f47), which is the only mode the kit can work in. But
it DID hold 054c:0d68 (PC Remote / HID) for 30 s, steadily. Sony's PTP extension has a command for exactly this need:

    PTP_OC_SonyReqReconnect = 0x9282     "Tells the camera to switch to mass storage mode"

If the FX2 answers PTP on 0d68 and lists 0x9282 in its OperationsSupported, then the camera can be moved to mass storage with one
small packet - needing ~1 second of a stable connection instead of ~5, and with no menu and no button. That is this probe's whole
question. Stage 2 (sending 0x9282) is separate and only worth building if this says yes.

  usage:  sudo ./ptp_probe.py            (sudo: macOS holds the HID device; libusb needs it released)
          ./.venv/bin/python ptp_probe.py --list     (no sudo: just show what USB sees)

What it prints, and what it means:
  device not found            the camera is not on USB right now (or not in PC Remote mode)
  GetDeviceInfo failed        the identity answers USB but not PTP -> the injection route does not exist there
  model / ops listed          model name, and whether 0x9282 is among the supported operations
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # the kit root (windows/ or macos/)
TOOLS = ROOT / "windows/tools/camera_tests/CT6_memory_read_check"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent.parent / "third_party/sony-pmca-re"))

SONY_VID = 0x054C
ID_PC_REMOTE = 0x0D68      # HID / PC Remote - the identity the camera held steadily
ID_MASS_STORAGE = 0x0F47   # mass storage - the mode the kit needs
ID_SERVICE = (0x0336, 0x02A9, 0x033A, 0x03E2)

NAMES = {ID_PC_REMOTE: "PC Remote (HID/MTP)", ID_MASS_STORAGE: "mass storage",
         0x0336: "SERVICE MODE", 0x02A9: "SERVICE MODE", 0x033A: "UPDATER", 0x03E2: "UPDATER"}


def list_devices():
    """Every Sony USB device and EVERY interface class it offers, from libusb (no claim, no I/O).

    All interfaces matter: a camera in PC Remote mode can be composite - a HID interface (buttons) beside a PTP one (control).
    Looking only at the first interface would report class 3 and wrongly conclude there is no PTP channel."""
    import usb.core
    out = []
    for dev in usb.core.find(find_all=True, idVendor=SONY_VID):
        classes = []
        try:
            for cfg in dev:
                for i in cfg:
                    classes.append(i.bInterfaceClass)
        except Exception as exc:                       # a device mid-enumeration throws here
            out.append((dev.idProduct, ["error: %s" % type(exc).__name__],
                        NAMES.get(dev.idProduct, "Sony device")))
            continue
        out.append((dev.idProduct, classes, NAMES.get(dev.idProduct, "Sony device")))
    return out


def has_ptp(classes):
    """True when any interface is class 6 (PTP/imaging), the class MtpContext needs."""
    return 6 in classes


def probe(product_id):
    """GetDeviceInfo over PTP against one product id. Read-only: one standard request."""
    from pmca.usb.driver.generic.libusb import MtpContext
    from pmca.usb.sony import SonyMtpExtCmdDevice
    print("opening %04x:%04x ..." % (SONY_VID, product_id))
    ctx = MtpContext()
    handle = next((d for d in _devices(product_id)), None)
    if handle is None:
        print("  the device is not present (it may have dropped off USB again)")
        return 2
    inner = ctx.openDevice(handle)
    try:
        dev = SonyMtpExtCmdDevice(inner)               # opens a PTP session in __init__
    except Exception as exc:
        print("  PTP session could not be opened: %s: %s" % (type(exc).__name__, exc))
        print("  -> this identity answers USB but not PTP; the 0x9282 route does not exist here.")
        return 3
    try:
        info = dev.getDeviceInfo()
    except Exception as exc:
        print("  GetDeviceInfo failed: %s: %s" % (type(exc).__name__, exc))
        return 4
    if info:
        print("  manufacturer: %s" % getattr(info, "manufacturer", "?"))
        print("  model:        %s" % getattr(info, "model", "?"))
        print("  serial:       %s" % getattr(info, "serialNumber", "?"))
        ops = getattr(info, "operationsSupported", set()) or set()
        want = 0x9282
        print("  operations supported: %d;  0x9282 (SonyReqReconnect) %s"
              % (len(ops), "IS LISTED -> the switch command is available" if want in ops
                 else "is NOT listed -> this body does not offer the switch over PTP"))
        print("  vendorExtension present: %s" % bool(getattr(info, "vendorExtension", None)))
    return 0


def _devices(product_id):
    import usb.core
    for dev in usb.core.find(find_all=True, idVendor=SONY_VID):
        if dev.idProduct == product_id:
            from pmca.usb.driver.generic.libusb import UsbDeviceHandle
            yield UsbDeviceHandle(dev, dev.idVendor, dev.idProduct)


def main():
    ap = argparse.ArgumentParser(description="Read-only PTP probe: can the FX2 be told to switch to mass storage?")
    ap.add_argument("--list", action="store_true", help="just list Sony USB devices; sends nothing")
    ap.add_argument("--id", type=lambda s: int(s, 16), default=ID_PC_REMOTE,
                    help="product id in hex to probe (default 0d68)")
    a = ap.parse_args()

    print("Sony USB devices libusb sees now:")
    found = list_devices()
    if not found:
        print("  none")
        print("\n  The camera is not on USB. Power it on in PC Remote mode (054c:0d68) and run again.")
        return 1
    for pid, classes, name in found:
        shown = ",".join(str(c) for c in classes) if classes else "-"
        ptp = "  [has PTP interface: class 6]" if has_ptp(classes) else "  [no PTP interface - class 6 absent]"
        print("  %04x:%04x  interface classes=%s  %s%s" % (SONY_VID, pid, shown, name, ptp))
    if a.list:
        return 0
    if a.id not in [p for p, _, _ in found]:
        print("\n%04x is not on USB right now." % a.id)
        return 1
    print()
    rc = probe(a.id)
    if rc == 0:
        print("\nRead-only probe finished. Nothing was sent to the camera except GetDeviceInfo.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
