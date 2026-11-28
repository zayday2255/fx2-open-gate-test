"""fx2cp.so against the camera's own libsencore.so: the same calls must make the same requests, byte for byte. Offline (Unicorn). (2026-11-28)

  C:\\Python313\\python.exe -B emu_fx2cp_diff.py

fx2cp.so gives a process outside the camera application the three functions the kit's step libraries take from libsencore.so. This runs
each of them twice, once from the camera's libsencore.so (FX2 1.01, the shipped file) and once from fx2cp.so, in an instruction emulator
where every call into another library (the message library, open / ioctl / close) is answered by the same model. Recorded per call: the
function called, its arguments, and for a message every byte of it (a message is handed out filled with 0xA5, so an unset field shows).
The two recordings must be equal, and so must what the functions return, for the normal path and for each failure the model can make:
the memory manager answers an error, no reply comes, the cache call is answered 0, /dev/pcidma cannot be opened, the ioctl fails.
Left out on both sides: what the camera's functions write to its log (cpp_logrec / logrec), and fx2cp.so's own line in /tmp_wbshd/fx2boot.log.
"""
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as R

HERE = Path(__file__).resolve().parent
SD = HERE.parent
ROOT = SD.parents[3]
SENCORE = ROOT / "work/extracted/fx2_101/0700_part_image/dev/nflasha15/lib/libsencore.so"
BASE, STUBS, HEAP, STACK, RET = 0x10000000, 0x30000000, 0x40000000, 0x50000000, 0x60000000
PHYS, HANDLE = 0x47F000000, 0x1234


class Lib:
    def __init__(self, path, model):
        self.model = model
        d = self.d = Path(path).read_bytes()
        uc = self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.mem_map(BASE, 0x200000)
        uc.mem_map(STUBS, 0x10000)
        uc.mem_map(HEAP, 0x100000)
        uc.mem_map(STACK - 0x100000, 0x100000)
        uc.mem_map(RET, 0x1000)
        phoff, = struct.unpack_from("<Q", d, 0x20)
        phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
        tags = {}
        for i in range(phnum):
            ptype, flags, off, vaddr, paddr, filesz, memsz, align = struct.unpack_from("<IIQQQQQQ", d, phoff + i * phentsize)
            if ptype == 1:
                uc.mem_write(BASE + vaddr, d[off:off + filesz])
            elif ptype == 2:
                for k in range(0, filesz, 16):
                    t, v = struct.unpack_from("<qQ", d, off + k)
                    if t == 0:
                        break
                    tags.setdefault(t, v)
        rd = lambda va, n: bytes(uc.mem_read(BASE + va, n))
        self.names, self.stubs = {}, {}

        def sym(index):
            name_off, info, other, shndx, value, size = struct.unpack("<IBBHQQ", rd(tags[6] + 24 * index, 24))
            name = rd(tags[5] + name_off, 96).split(b"\0")[0].decode()
            return name, shndx, value

        def target(index):
            name, shndx, value = sym(index)
            if shndx != 0 and "logrec" not in name:
                return BASE + value                              # the library's own function or object
            if name not in self.stubs:
                self.stubs[name] = STUBS + 16 * len(self.stubs)
                self.names[self.stubs[name]] = name
                uc.mem_write(self.stubs[name], struct.pack("<I", 0xD65F03C0))        # ret
            return self.stubs[name]

        for table, size in ((tags.get(7), tags.get(8, 0)), (tags.get(23), tags.get(2, 0))):
            for i in range(size // 24):
                r_off, r_info, r_add = struct.unpack("<QQq", rd(table + 24 * i, 24))
                kind = r_info & 0xFFFFFFFF
                if kind == 1027:                                 # RELATIVE
                    uc.mem_write(BASE + r_off, struct.pack("<Q", BASE + r_add))
                elif kind in (1025, 1026, 257):                  # GLOB_DAT, JUMP_SLOT, ABS64
                    uc.mem_write(BASE + r_off, struct.pack("<Q", (target(r_info >> 32) + (r_add if kind == 257 else 0)) & 0xFFFFFFFFFFFFFFFF))
                else:
                    raise SystemExit("unexpected relocation type %d in %s" % (kind, path))
        self.exports = {}
        n = 0
        for i in range(1, 4096):
            try:
                name, shndx, value = sym(i)
            except Exception:
                break
            if shndx != 0 and name:
                self.exports[name] = BASE + value
            n += 1
            if tags[6] + 24 * (i + 1) >= tags[5] > tags[6]:
                break
        uc.hook_add(UC_HOOK_CODE, self.on_stub, begin=STUBS, end=STUBS + 0xFFFF)

    def x(self, n):
        return self.uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))

    def on_stub(self, uc, address, size, _):
        name = self.names.get(address, "?")
        ret = self.model.call(self, name)
        uc.reg_write(R.UC_ARM64_REG_X0, ret & 0xFFFFFFFFFFFFFFFF)

    def call(self, name, *args):
        uc = self.uc
        for i, a in enumerate(args):
            uc.reg_write(getattr(R, "UC_ARM64_REG_X%d" % i), a & 0xFFFFFFFFFFFFFFFF)
        uc.reg_write(R.UC_ARM64_REG_SP, STACK - 0x1000)
        uc.reg_write(R.UC_ARM64_REG_X30, RET)
        uc.emu_start(self.exports[name], RET, count=5_000_000)
        if uc.reg_read(R.UC_ARM64_REG_PC) != RET:
            raise SystemExit("%s did not return" % name)
        return uc.reg_read(R.UC_ARM64_REG_X0)


class Model:
    """The other libraries, the same for both sides. `fail` picks one failure."""

    def __init__(self, fail=None):
        self.fail, self.trace, self.heap, self.sizes, self.src, self.reply = fail, [], HEAP, {}, {}, None
        self.dyn = 0

    def alloc(self, lib, size, fill):
        a = self.heap
        self.heap += (size + 31) & ~15
        lib.uc.mem_write(a, bytes([fill]) * size)
        self.sizes[a] = size
        return a

    def msg(self, lib, a):
        return bytes(lib.uc.mem_read(a, self.sizes[a])).hex()

    def call(self, lib, name):
        x, uc, t = lib.x, lib.uc, self.trace
        if "logrec" in name or name in ("write", "__errno_location", "__stack_chk_fail"):
            if name == "__errno_location":
                return self.alloc(lib, 8, 0)
            return 0                                             # logging: not part of the comparison
        if name == "osal_dynamic_id":
            op, kind, arg = x(0) & 0xFFFFFFFF, x(1) & 0xFFFFFFFF, x(2)
            if op == 0x2a:
                self.dyn = 0x7F3D0001
                uc.mem_write(arg, struct.pack("<I", self.dyn))
                t.append(("dynamic_id", op, kind, "pointer"))
            else:
                t.append(("dynamic_id", op, kind, arg & 0xFFFFFFFF))
            return 0
        if name == "osal_valloc_msg_wait":
            q, pmsg, size, wait = x(0) & 0xFFFFFFFF, x(1), x(2) & 0xFFFFFFFF, x(3) & 0xFFFFFFFF
            a = self.alloc(lib, size, 0xA5)
            uc.mem_write(pmsg, struct.pack("<Q", a))
            t.append(("valloc", q, size, wait))
            return 0
        if name == "osal_set_msg_src":
            self.src[x(0)] = x(1) & 0xFFFFFFFF
            t.append(("set_src", x(1) & 0xFFFFFFFF))
            return 0
        if name == "osal_snd_msg":
            q, m = x(0) & 0xFFFFFFFF, x(1)
            t.append(("snd", q, self.msg(lib, m), self.src.get(m)))
            op = struct.unpack("<H", bytes(uc.mem_read(m, 2)))[0]
            r = self.alloc(lib, 0x28, 0)
            if op == 0x20 and self.fail == "dmm":
                uc.mem_write(r + 2, struct.pack("<h", -5))
            elif op == 0x20 and self.fail == "small":
                uc.mem_write(r + 0xc, struct.pack("<I", HANDLE)); uc.mem_write(r + 0x18, struct.pack("<Q", PHYS)); uc.mem_write(r + 0x20, struct.pack("<I", 0x800))
            elif op == 0x20:
                uc.mem_write(r + 0xc, struct.pack("<I", HANDLE)); uc.mem_write(r + 0x18, struct.pack("<Q", PHYS)); uc.mem_write(r + 0x20, struct.pack("<I", 0x2000))
            self.reply = None if self.fail == "no_reply" else r
            return 0x77 if self.fail == "send" else 0
        if name == "osal_rcv_msg_tmo":
            t.append(("rcv", x(0) & 0xFFFFFFFF, x(2) & 0xFFFFFFFF))
            if self.reply is None:
                return 0xFFFFFC02
            uc.mem_write(x(1), struct.pack("<Q", self.reply))
            return 0
        if name == "osal_free_msg":
            t.append(("free", x(0) & 0xFFFFFFFF, "reply" if x(1) == self.reply else "request"))
            return 0
        if name == "osal_snd_sync_msg":
            q, m = x(0) & 0xFFFFFFFF, x(1)
            t.append(("snd_sync", q, self.msg(lib, m)))
            uc.mem_write(m + 1, bytes([0 if self.fail == "cache" else 1]))
            return 0x55 if self.fail == "sync" else 0
        if name == "open":
            path = bytes(uc.mem_read(x(0), 64)).split(b"\0")[0].decode()
            if path == "/tmp_wbshd/fx2boot.log":                 # fx2cp.so's own line about a failure: not part of the comparison
                return 9
            t.append(("open", path, x(1) & 0xFFFFFFFF))
            return 0xFFFFFFFFFFFFFFFF if self.fail == "open" else 7
        if name == "ioctl":
            t.append(("ioctl", x(0) & 0xFFFFFFFF, x(1) & 0xFFFFFFFF, bytes(uc.mem_read(x(2), 24)).hex()))
            return 0xFFFFFFFFFFFFFFFF if self.fail == "ioctl" else 0
        if name == "close":
            if x(0) & 0xFFFFFFFF != 9:
                t.append(("close", x(0) & 0xFFFFFFFF))
            return 0
        raise SystemExit("call of %r, which the model does not have" % name)


def run(path, fail):
    m = Model(fail)
    lib = Lib(path, m)
    out = lib.alloc_out = m.alloc(lib, 8, 0)
    res = []
    phys = lib.call("_Z9dmm_allocjPj", 0x1000, out)
    res.append(("dmm_alloc", phys, struct.unpack("<I", bytes(lib.uc.mem_read(out, 4)))[0]))
    res.append(("transfer read", lib.call("sen_dma_transfer", 0, 0x192FC00, PHYS, 0x40) & 0xFFFFFFFF))
    res.append(("transfer write", lib.call("sen_dma_transfer", 1, PHYS, 0x24DE600, 0x1000) & 0xFFFFFFFF))
    lib.call("_Z8dmm_freej", HANDLE)
    res.append(("dmm_free", "returned"))
    return m.trace, res


def main():
    fail_count = 0
    for fail in (None, "dmm", "small", "no_reply", "send", "cache", "sync", "open", "ioctl"):
        t0, r0 = run(SENCORE, fail)
        t1, r1 = run(SD / "fx2cp.so", fail)
        nz = lambda v: v != 0
        same_ret = all(a[0] == b[0] and (a[1:] == b[1:] or (a[0].startswith("transfer") and nz(a[1]) and nz(b[1]))) for a, b in zip(r0, r1))
        good = t0 == t1 and same_ret and len(r0) == len(r1)
        fail_count += not good
        print("%s  %-9s %2d calls into the other libraries, identical in order, arguments and every message byte; results %s"
              % ("PASS" if good else "FAIL", fail or "normal", len(t0), "equal" if same_ret else "DIFFER"))
        if not good:
            for i, (a, b) in enumerate(zip(t0, t1)):
                if a != b:
                    print("   first difference at call %d:\n     camera's: %s\n     fx2cp   : %s" % (i, a, b))
                    break
            print("   results camera's %s\n   results fx2cp    %s" % (r0, r1))
        if fail is None:
            for e in t0:
                print("        " + " ".join(str(v) if not isinstance(v, int) else hex(v) for v in e)[:230])
    print("ALL PASS" if not fail_count else "FAILED: %d" % fail_count)
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
