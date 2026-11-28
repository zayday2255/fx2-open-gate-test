"""Shared pieces of camera test CT1 (first contact over USB-C, reads only).

Holds the things every stage relies on:
  - where files go (raw results stay outside the map's git repository)
  - the check that PMCA-RE is the pinned, unmodified checkout
  - the session log and manifest, written even when a stage fails
  - the guards: the only packets CT1 can send are listed in this file

Run every CT1 script with the camera environment, isolated:
  work\\venv_camera\\Scripts\\python.exe -I -B camera_tests\\CT1_usb_first_contact\\<script>.py
"""
import hashlib
import json
import plistlib
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAP_ROOT = HERE.parent.parent                 # ...\A7iv Firmware\a7iv_map
REPO = MAP_ROOT.parent                        # ...\A7iv Firmware
CAMERA_RE = MAP_ROOT / "third_party"
PMCA_ROOT = CAMERA_RE / "sony-pmca-re"
PMCA_COMMIT = "a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0"
BK4_DIR = CAMERA_RE / "a7iv" / "sony-a7iv-feature-research" / "scripts"
PRIVATE_ROOT = REPO / "camera_private"        # outside the map's git repository
PREDICTIONS = HERE / "predictions.json"
CORE_DB = MAP_ROOT / "a7iv.sqlite"
EXTRACTED = MAP_ROOT / "reference" / "a7iv_602"

SONY_VID = 0x054C
EXPECTED_MODEL = "ILCE-7M4"
EXPECTED_FIRMWARE = "6.02"


class StopTest(Exception):
    """A stop rule fired. The stage ends; nothing is retried."""


class GuardRefusal(StopTest):
    """A packet outside the allowlist was about to be sent. Nothing was written."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# PMCA-RE: pinned commit, unmodified, imported from its checkout
# --------------------------------------------------------------------------

def check_pmca():
    """Return the pinned PMCA-RE commit after confirming the vendored files are the published ones, unmodified (PINNED.json)."""
    pinned = json.loads((PMCA_ROOT / "PINNED.json").read_text(encoding="utf-8"))
    if pinned["commit"] != PMCA_COMMIT:
        raise StopTest("vendored PMCA-RE is %s, expected %s" % (pinned["commit"], PMCA_COMMIT))
    for rel, want in pinned["files"].items():
        path = PMCA_ROOT / rel
        if not path.is_file() or sha256(path.read_bytes()) != want:
            raise StopTest("PMCA-RE file %s is missing or modified" % rel)
    extra = sorted(p.relative_to(PMCA_ROOT).as_posix() for p in (PMCA_ROOT / "pmca").rglob("*.py")
                   if p.relative_to(PMCA_ROOT).as_posix() not in pinned["files"])
    if extra:
        raise StopTest("PMCA-RE folder has files that are not pinned: %s" % ", ".join(extra))
    return PMCA_COMMIT


def use_pmca():
    """Make the pmca package importable. Only pmca.usb.* is ever imported by CT1."""
    check_pmca()
    root = str(PMCA_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    if sys.platform == "darwin":
        use_bundled_libusb()


def use_bundled_libusb():
    """macOS: load libusb from the libusb-package wheel (macos/requirements.txt), so no Homebrew is needed. pyusb keeps
    the first backend it loads, so PMCA-RE's own usb.core.find calls use this one. Without the wheel, pyusb looks for a
    system libusb itself."""
    try:
        import libusb_package
    except ImportError:
        return
    libusb_package.get_libusb1_backend()


def use_bk4():
    """The read-only BK4 parser the map's own pipeline already uses."""
    path = str(BK4_DIR)
    if path not in sys.path:
        sys.path.append(path)
    import bk4
    return bk4


# --------------------------------------------------------------------------
# Session: log, manifest, files. Written in every case.
# --------------------------------------------------------------------------

class Session:
    def __init__(self, stage, write=True, root=None, test="CT1"):
        self.stage = stage
        self.test = test
        self.write = write
        self.t0 = time.monotonic()
        self.events = []
        self.files = {}
        self.results = {}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.started_utc = stamp
        self.dir = None
        if write:
            self.dir = Path(root or PRIVATE_ROOT) / ("%s_%s_%s" % (test, stamp, stage))
            self.dir.mkdir(parents=True, exist_ok=False)

    def log(self, kind, **fields):
        event = {"t": round(time.monotonic() - self.t0, 4), "kind": kind}
        event.update(fields)
        self.events.append(event)
        return event

    def say(self, text):
        self.log("note", text=text)
        print(text, flush=True)

    def save_bytes(self, name, data):
        digest = sha256(data)
        self.files[name] = {"bytes": len(data), "sha256": digest}
        if self.write:
            with (self.dir / name).open("xb") as out:   # never overwrites
                out.write(data)
        self.log("file_saved", name=name, bytes=len(data), sha256=digest)
        return digest

    def save_json(self, name, obj):
        return self.save_bytes(name, (json.dumps(obj, indent=1) + "\n").encode("utf-8"))

    def finish(self, status, error=None):
        manifest = {
            "test": self.test,
            "stage": self.stage,
            "started_utc": self.started_utc,
            "status": status,
            "error": error,
            "pmca_commit": PMCA_COMMIT,
            "predictions_sha256": sha256(PREDICTIONS.read_bytes()) if PREDICTIONS.exists() else None,
            "python": sys.version.split()[0],
            "files": self.files,
            "results": self.results,
        }
        if self.write:
            (self.dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
            with (self.dir / "transcript.jsonl").open("w", encoding="utf-8") as out:
                for event in self.events:
                    out.write(json.dumps(event) + "\n")
            print("Session folder: %s" % self.dir, flush=True)
        print("Stage %s: %s%s" % (self.stage, status, (" (%s)" % error) if error else ""), flush=True)
        return manifest

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self.finish("completed")
            return False
        status = "stopped" if isinstance(exc, StopTest) else "failed"
        self.finish(status, "%s: %s" % (exc_type.__name__, exc))
        return isinstance(exc, StopTest)        # a stop rule is a clean end, not a crash


def mask_instance_id(instance_id):
    """Keep VID/PID, hide the serial part of a Windows device instance id."""
    parts = instance_id.split("\\")
    if len(parts) >= 3 and len(parts[-1]) > 4:
        parts[-1] = "***" + parts[-1][-2:]
    return "\\".join(parts)


def mask_serial(serial):
    return ("***" + serial[-2:]) if serial and len(serial) > 2 else "***"


OS_NAME = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, sys.platform)


def pnp_sony_devices():
    """Sony USB devices the OS shows as present, with class and driver service. Read-only."""
    if sys.platform == "darwin":
        return ioreg_sony_devices()
    command = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -match 'VID_054C' } | "
               "Select-Object PNPDeviceID, PNPClass, Name, Service, Status | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        rows = json.loads(out) if out else []
    except Exception as exc:                    # listing is evidence only; never fatal
        return [{"error": str(exc)}]
    if isinstance(rows, dict):
        rows = [rows]
    return [{"instance_id": r.get("PNPDeviceID"), "class": r.get("PNPClass"), "name": r.get("Name"),
             "service": r.get("Service"), "status": r.get("Status")} for r in rows]


def ioreg_sony_devices():
    """Sony USB devices macOS shows as present, from the I/O Registry: interface classes, the drivers on the
    interfaces, and the whole disks under the device (the memory card in Mass Storage mode). Read-only.

    `ioreg -r` lists only the outermost matches, so a camera behind a hub or dock sits inside the hub's entry:
    the whole tree is searched."""
    try:
        out = subprocess.run(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l"], capture_output=True, timeout=60).stdout
        tops = plistlib.loads(out) if out.strip() else []
    except Exception as exc:                    # listing is evidence only; never fatal
        return [{"error": str(exc)}]
    rows = []
    for dev in (n for top in tops for n in _walk(top)):
        if dev.get("IOObjectClass") != "IOUSBHostDevice" or dev.get("idVendor") != SONY_VID:
            continue
        interfaces = [n for n in dev.get("IORegistryEntryChildren", []) if n.get("IOObjectClass") == "IOUSBHostInterface"]
        drivers = [d.get("IOObjectClass") for i in interfaces for d in i.get("IORegistryEntryChildren", [])]
        disks = {n["BSD Name"] for n in _walk(dev) if n.get("IOObjectClass") == "IOMedia" and n.get("Whole") and n.get("BSD Name")}
        rows.append({"instance_id": "USB %04X:%04X at 0x%08x" % (SONY_VID, dev.get("idProduct", 0), dev.get("locationID", 0)),
                     "class": ",".join(str(i.get("bInterfaceClass")) for i in interfaces) or None,
                     "name": dev.get("USB Product Name"), "service": ",".join(dict.fromkeys(drivers)) or "none", "status": None,
                     "disks": sorted(disks)})
    return rows


def _walk(node):
    """An I/O Registry entry from `ioreg -a` and everything under it."""
    yield node
    for child in node.get("IORegistryEntryChildren", []):
        yield from _walk(child)


def unmount_sony_disks(session):
    """macOS: unmount the camera's memory card before its mass-storage driver is taken away, so nothing the Mac was
    writing to the card is cut off. Unmount only: the card is not ejected and nothing is written to it. Stops when
    the camera can't be found in the I/O Registry: its card might still be mounted."""
    rows = ioreg_sony_devices()
    session.log("pnp", label="before the unmount", devices=rows)
    if not rows or any("error" in r for r in rows):
        raise StopTest("the camera was not found in the macOS I/O Registry, so its memory card could not be unmounted "
                       "(%s). Nothing was sent" % (rows[0]["error"] if rows else "no Sony USB device listed"))
    for row in rows:
        for disk in row["disks"]:
            r = subprocess.run(["diskutil", "unmountDisk", "/dev/" + disk], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                # Spotlight indexing the card can hold it (issue 7): switch indexing off for the camera's card and retry once.
                session.log("unmount", disk=disk, code=r.returncode, out=(r.stdout + r.stderr).strip(), retry="mdutil -i off")
                for vol in Path("/Volumes").glob("*/PRIVATE/M4ROOT"):
                    subprocess.run(["mdutil", "-i", "off", str(vol.parents[1])], capture_output=True, timeout=30)
                time.sleep(2)
                r = subprocess.run(["diskutil", "unmountDisk", "/dev/" + disk], capture_output=True, text=True, timeout=60)
            text = (r.stdout + r.stderr).strip()
            session.log("unmount", disk=disk, code=r.returncode, out=text)
            if r.returncode != 0:
                raise StopTest("macOS could not unmount the camera's memory card (%s: %s). Close any app showing it "
                               "(Finder, Photos, Image Capture) and run again" % (disk, text))
            session.say("Unmounted the camera's memory card (%s)" % disk)


def print_pnp(session, label):
    rows = pnp_sony_devices()
    session.log("pnp", label=label, devices=rows)
    print("Sony USB devices %s shows (%s):" % (OS_NAME, label))
    for r in rows:
        if "error" in r:
            print("  (listing failed: %s)" % r["error"])
        else:
            print("  %-34s class=%-10s driver=%-12s %s" % (
                mask_instance_id(r["instance_id"] or ""), r["class"], r["service"], r["name"]))
    if not rows:
        print("  none")
    return rows


# --------------------------------------------------------------------------
# Guard 1: service ("Senser") packets. The complete list of what CT1 may send.
# --------------------------------------------------------------------------

PFUNC_PRODUCT_INFO = 0x10
PFUNC_ADJUST = 0x40

PROBE_PATHS = (
    b"../../usr/share/pmbp/DeviceInfo.xml",
    b"../../proc/cmdline",
)

# (packet type, category, code) -> (name, payload test)
_SERVICE_RULES = {
    (PFUNC_PRODUCT_INFO, 0x0000, 0x001F): ("READ_HASP", lambda p: p == b"\x00"),
    (PFUNC_ADJUST, 0x0603, 0x0005): ("BACKUP_READ_FROM_MEMORY", lambda p: p == b"\x01"),
    (PFUNC_ADJUST, 0x1001, 0x400F): ("SET_FILE_PATH", lambda p: p[:1] == b"\x00" and p[1:] in PROBE_PATHS),
    (PFUNC_ADJUST, 0x1001, 0x4011): ("GET_FILE2", lambda p: p == b"\x00\xff\x00"),
}

_PFUNC_NAMES = {0x10: "product info", 0x20: "firmware update", 0x30: "microcontroller access",
                0x40: "adjust", 0xFF00: "test mode", 0xFF01: "file control", 0xFF02: "sonar",
                0xFF03: "memory dump"}


def classify_service_packet(pfunc, data, rules=None):
    """Name an allowed packet, or raise GuardRefusal. Pure function: nothing is sent here."""
    kind = _PFUNC_NAMES.get(pfunc, "unknown")
    if len(data) < 4:
        raise GuardRefusal("service packet type 0x%x (%s) with a %d-byte body" % (pfunc, kind, len(data)))
    category, code = struct.unpack_from("<HH", data, 0)
    payload = bytes(data[4:])
    rule = (_SERVICE_RULES if rules is None else rules).get((pfunc, category, code))
    if rule is None:
        extra = ""
        if pfunc == PFUNC_ADJUST and category == 0x060B:
            extra = " This is the coprocessor debug group (NOR read/write); it is never sent."
        raise GuardRefusal("service packet type 0x%x (%s), category 0x%x, code 0x%x is not on this test's list.%s"
                           % (pfunc, kind, category, code, extra))
    name, payload_ok = rule
    if not payload_ok(payload):
        raise GuardRefusal("%s with a payload this test does not use: %s" % (name, payload[:64].hex()))
    return name


SENSER_HEADER = "<IHHBBBB"          # size, packet type, sequence, version, micon type, offset type, response
SENSER_HEADER_SIZE = struct.calcsize(SENSER_HEADER)
SENSER_PART_MAX = 0x100000
USB_PACKET = 512


def read_service_answer(driver, sequence, log=None):
    """Read one service answer: (response code, data). Our own reader; it sends nothing.

    PMCA-RE's reader reads 512 bytes after every 0x8000 and throws them away. On Windows with
    libusb-win32 this camera sends no padding there, so that reader drops real data, drifts, and
    fails after the first megabyte (seen 2026-11-13 on the settings backup, session
    CT1_20261113T080109Z). What the camera did send: a 12-byte header as its own short transfer,
    then that part's data as one run, at most 1 MB per part, then the next header.

    Every read asks for a multiple of the 512-byte packet size and never for more than the part
    still owes, so a read cannot overflow and cannot swallow the next header.
    """
    def read_header():
        for _ in range(4):                               # tolerate empty reads (zero-length packets)
            raw = driver.read(SENSER_HEADER_SIZE)
            if raw:
                break
        if len(raw) != SENSER_HEADER_SIZE:
            raise StopTest("service answer header is %d bytes, expected %d" % (len(raw), SENSER_HEADER_SIZE))
        return struct.unpack(SENSER_HEADER, raw)

    out = bytearray()
    total = None
    while True:
        size, pfunc, seq, _version, _micon, _offset, response = read_header()
        if log:
            log("service_header", size=size, pfunc=pfunc, sequence=seq, response=response, have=len(out))
        if seq != sequence:
            raise StopTest("service answer has sequence %d, expected %d" % (seq, sequence))
        if total is None:
            total = size
        part = min(total - len(out), SENSER_PART_MAX)
        got = 0
        empty = 0
        while got < part:
            want = min(part - got, 0x8000)
            chunk = driver.read((want + USB_PACKET - 1) // USB_PACKET * USB_PACKET)
            if not chunk:
                empty += 1
                if empty > 4:
                    raise StopTest("service answer stalled at %d of %d bytes" % (len(out) + got, total))
                continue
            if len(chunk) > want:
                raise StopTest("service answer overran its part by %d bytes" % (len(chunk) - want))
            empty = 0
            out += chunk
            got += len(chunk)
        if len(out) >= total:
            return response, bytes(out)


class ServiceGuard:
    """Wraps a PMCA SonySenserDevice so only listed packets leave, and logs each one.

    Outgoing packets are built exactly as PMCA-RE builds them (header + body); the answer is
    read by read_service_answer above instead of PMCA-RE's reader.
    """

    def __init__(self, senser_device, session, rules=None):
        self.session = session
        self.rules = rules
        self._device = senser_device
        self._path_set = None
        senser_device.sendSenserPacket = self.send

    def _send(self, pFunc, data, _oData):
        device = self._device
        if len(data) > 0x1000:
            raise GuardRefusal("a %d-byte service packet: CT1 sends only small requests" % len(data))
        header = struct.pack(SENSER_HEADER, len(data), pFunc, device._sequence, 0, 0, 0, 0)
        device.driver.write(header + bytes(data))
        response, out = read_service_answer(device.driver, device._sequence, self.session.log)
        device._sequence += 1
        return response, out

    def send(self, pFunc, data, oData=None):
        name = classify_service_packet(pFunc, data, self.rules)  # raises before any write
        if oData is not None:
            raise GuardRefusal("%s: output redirection is not used in CT1" % name)
        if name == "GET_FILE2" and self._path_set is None:
            raise GuardRefusal("GET_FILE2 without a SET_FILE_PATH from this session just before it")
        self.session.log("service_out", name=name, pfunc=pFunc, bytes=len(data), hex=bytes(data).hex())
        response, out = self._send(pFunc, data, None)
        self.session.log("service_in", name=name, response=response, bytes=len(out), sha256=sha256(out))
        self._path_set = bytes(data[5:]) if (name == "SET_FILE_PATH" and response == 0) else None
        return response, out


# --------------------------------------------------------------------------
# Guard 2: the raw USB driver under the service protocol.
# --------------------------------------------------------------------------

VENDOR_REQUESTS = {
    (1, 0x37FF, 0xD7AA): "START_SENSER",
    (1, 0xC800, 0x2855): "STOP_SENSER",
}


class GuardedDriver:
    """Stands in for a PMCA GenericUsbDriver. Bulk endpoint 0 only, two vendor requests only.

    There is no pass-through for anything else: an unknown attribute is an error.
    """

    def __init__(self, inner, session, label):
        self._inner = inner
        self._session = session
        self._label = label

    def getId(self):
        return self._inner.getId()

    def reset(self):
        self._inner.reset()

    def read(self, length, ep=0, timeout=None):
        if ep != 0:
            raise GuardRefusal("read on endpoint index %d (the terminal channel) is not used in CT1" % ep)
        data = self._inner.read(length, ep, timeout)
        self._session.log("usb_in", dev=self._label, asked=length, bytes=len(data), head=bytes(data[:12]).hex())
        return data

    def write(self, data, ep=0):
        if ep != 0:
            raise GuardRefusal("write on endpoint index %d (the terminal channel) is not used in CT1" % ep)
        self._session.log("usb_out", dev=self._label, bytes=len(data), head=bytes(data[:12]).hex())
        self._inner.write(data, ep)

    def vendorRequestOut(self, request, value, index, data=b""):
        name = VENDOR_REQUESTS.get((request, value, index))
        if name is None or data:
            raise GuardRefusal("vendor request (%d, 0x%04x, 0x%04x) with %d data bytes is not on the CT1 list"
                               % (request, value, index, len(data)))
        self._session.log("usb_vendor_out", dev=self._label, name=name, request=request,
                          value="0x%04x" % value, index="0x%04x" % index)
        self._inner.vendorRequestOut(request, value, index, data)


# --------------------------------------------------------------------------
# Guard 3: PTP operations for the PC Remote snapshot.
# --------------------------------------------------------------------------

PTP_GET_DEVICE_INFO = 0x1001
PTP_OPEN_SESSION = 0x1002
SDIO_CONNECT = 0x9201
SDIO_GET_EXT_DEVICE_INFO = 0x9202
SDIO_GET_ALL_EXT_DEVICE_PROP_INFO = 0x9209
SONY_PROTOCOL_3_00 = 0x012C

PTP_NO_DATA = {
    (PTP_OPEN_SESSION, (1,)): "OpenSession",
}
PTP_DATA_IN = {
    (PTP_GET_DEVICE_INFO, ()): "GetDeviceInfo",
    (SDIO_CONNECT, (1, 0, 0)): "SDIOConnect phase 1",
    (SDIO_CONNECT, (2, 0, 0)): "SDIOConnect phase 2",
    (SDIO_CONNECT, (3, 0, 0)): "SDIOConnect phase 3",
    (SDIO_GET_EXT_DEVICE_INFO, (SONY_PROTOCOL_3_00, 1)): "SDIOGetExtDeviceInfo",
    (SDIO_GET_ALL_EXT_DEVICE_PROP_INFO, ()): "SDIOGetAllExtDevicePropInfo",
}


class GuardedPtpDriver:
    """Stands in for a PMCA MTP driver. Listed operations only; nothing with data going out."""

    def __init__(self, inner, session):
        self._inner = inner
        self._session = session

    def reset(self):
        self._inner.reset()

    def _name(self, table, code, args, what):
        name = table.get((code, tuple(args)))
        if name is None:
            raise GuardRefusal("PTP operation 0x%04x%s (%s) is not on the CT1 list" % (code, list(args), what))
        return name

    def sendCommand(self, code, args):
        name = self._name(PTP_NO_DATA, code, args, "no data")
        self._session.log("ptp_out", name=name, code="0x%04x" % code, args=list(args))
        response = self._inner.sendCommand(code, list(args))
        self._session.log("ptp_in", name=name, response="0x%04x" % response)
        return response

    def sendReadCommand(self, code, args):
        name = self._name(PTP_DATA_IN, code, args, "data in")
        self._session.log("ptp_out", name=name, code="0x%04x" % code, args=list(args))
        response, data = self._inner.sendReadCommand(code, list(args))
        self._session.log("ptp_in", name=name, response="0x%04x" % response,
                          bytes=len(data), sha256=sha256(data))
        return response, data

    def sendWriteCommand(self, code, args, data):
        raise GuardRefusal("PTP operation 0x%04x with data going to the camera: CT1 sends none" % code)


# --------------------------------------------------------------------------
# PTP parsers (our own; layout checked against the public A7 IV research)
# --------------------------------------------------------------------------

_SCALARS = {0x0001: ("INT8", "b"), 0x0002: ("UINT8", "B"), 0x0003: ("INT16", "h"), 0x0004: ("UINT16", "H"),
            0x0005: ("INT32", "i"), 0x0006: ("UINT32", "I"), 0x0007: ("INT64", "q"), 0x0008: ("UINT64", "Q")}
_ARRAY = 0x4000
_STRING = 0xFFFF


def _ptp_string(data, offset):
    count = data[offset]
    end = offset + 1 + 2 * count
    if end > len(data):
        raise ValueError("truncated PTP string")
    return data[offset + 1:end].decode("utf-16le", "replace").rstrip("\0"), end


def _u16_array(data, offset):
    (count,) = struct.unpack_from("<I", data, offset)
    end = offset + 4 + 2 * count
    if end > len(data):
        raise ValueError("truncated 16-bit array")
    return list(struct.unpack_from("<%dH" % count, data, offset + 4)), end


def parse_device_info(data):
    """Standard PTP DeviceInfo dataset."""
    standard_version, vendor_ext_id, vendor_ext_version = struct.unpack_from("<HIH", data, 0)
    vendor_ext_desc, o = _ptp_string(data, 8)
    (functional_mode,) = struct.unpack_from("<H", data, o)
    o += 2
    operations, o = _u16_array(data, o)
    events, o = _u16_array(data, o)
    properties, o = _u16_array(data, o)
    capture_formats, o = _u16_array(data, o)
    image_formats, o = _u16_array(data, o)
    manufacturer, o = _ptp_string(data, o)
    model, o = _ptp_string(data, o)
    device_version, o = _ptp_string(data, o)
    serial, o = _ptp_string(data, o)
    return {"standard_version": standard_version, "vendor_extension_id": vendor_ext_id,
            "vendor_extension_version": vendor_ext_version, "vendor_extension_desc": vendor_ext_desc,
            "functional_mode": functional_mode, "operations": operations, "events": events,
            "properties": properties, "capture_formats": capture_formats, "image_formats": image_formats,
            "manufacturer": manufacturer, "model": model, "device_version": device_version, "serial": serial}


def parse_ext_device_info(data):
    """Sony SDIOGetExtDeviceInfo: version, property codes, control codes."""
    (version,) = struct.unpack_from("<H", data, 0)
    properties, o = _u16_array(data, 2)
    controls, o = _u16_array(data, o)
    return {"version": version, "properties": properties, "controls": controls, "trailing": len(data) - o}


def _ptp_value(data, offset, datatype):
    if datatype == _STRING:
        return _ptp_string(data, offset)
    if datatype & _ARRAY:
        (count,) = struct.unpack_from("<I", data, offset)
        if count > 10000:
            raise ValueError("unreasonable array count %d" % count)
        offset += 4
        values = []
        for _ in range(count):
            value, offset = _ptp_value(data, offset, datatype & ~_ARRAY)
            values.append(value)
        return values, offset
    if datatype not in _SCALARS:
        raise ValueError("unsupported PTP datatype 0x%04x" % datatype)
    fmt = "<" + _SCALARS[datatype][1]
    return struct.unpack_from(fmt, data, offset)[0], offset + struct.calcsize(fmt)


def datatype_name(datatype):
    if datatype == _STRING:
        return "STRING"
    base = _SCALARS.get(datatype & ~_ARRAY, ("UNKNOWN",))[0]
    return base + ("[]" if datatype & _ARRAY else "")


def parse_all_prop_info(data):
    """Sony protocol 3 aggregate property block: a count, then one descriptor per property."""
    count, _reserved = struct.unpack_from("<II", data, 0)
    o = 8
    out = []
    for _ in range(count):
        start = o
        code, datatype, get_set, enabled = struct.unpack_from("<HHBB", data, o)
        o += 6
        default, o = _ptp_value(data, o, datatype)
        current, o = _ptp_value(data, o, datatype)
        form = data[o]
        o += 1
        d = {"code": code, "datatype": datatype, "datatype_name": datatype_name(datatype),
             "get_set": get_set, "enabled": enabled, "default": default, "current": current, "form": form}
        if form == 1:
            d["range"] = []
            for _ in range(3):
                value, o = _ptp_value(data, o, datatype)
                d["range"].append(value)
        elif form == 2:
            for key in ("enum", "enum_secondary"):
                # A second value list may follow the first. The next descriptor would start
                # with a property code (0x5000 or higher), so a small number here is a count.
                if key == "enum_secondary" and not (o + 2 <= len(data)
                                                    and struct.unpack_from("<H", data, o)[0] < 0x0200):
                    break
                (n,) = struct.unpack_from("<H", data, o)
                o += 2
                d[key] = []
                for _ in range(n):
                    value, o = _ptp_value(data, o, datatype)
                    d[key].append(value)
        elif form != 0:
            raise ValueError("descriptor 0x%04x: unknown form %d" % (code, form))
        d["size"] = o - start
        out.append(d)
    if o != len(data):
        raise ValueError("decoded %d of %d bytes" % (o, len(data)))
    return out
