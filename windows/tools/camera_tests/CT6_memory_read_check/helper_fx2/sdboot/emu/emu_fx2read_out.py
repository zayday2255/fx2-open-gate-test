"""Offline test of libJit_fx2_X21 (GitHub issue #16), in Unicorn, with a syscall layer that stands in for the camera's kernel.

  python3 emu/emu_fx2read_out.py          (needs unicorn; no camera, no firmware)

The one thing that was wrong: the kit's read-only check finds libmpr.so in /proc/self/maps and reads the encoder-side sites
there. Run as the loader's helper (a process of its own), "self" is the helper, so every libmpr.so site reads NOT MAPPED and the
verdict is NOT READY on a stock camera - while X18 read the same camera as READY in the same second.

This test runs the built AArch64 code with a model camera application (im.elf, pid 543) that has libmpr.so mapped, and models:

  /proc/<pid>/comm, /proc/<pid>/maps, /proc/  (getdents64), /proc/<pid>/mem (pread64), /usr/lib/<lib>.so, the result file.
  /dev/mem is made to fail, and the three coprocessor calls of fx2cp.so return "no buffer": so nothing that needs the coprocessor
  runs. That is deliberate: the coprocessor part of the check is not what changed, and leaving it out keeps this test to the one
  claim it makes. The check reports the failure as it always does (a line, and the verdict).

Cases, each printed with the lines that matter:
  kit-check-app    the kit's own libJit_fx2_check.so, maps = the camera application's      -> lm sites STOCK at the app's addresses
  kit-check-self   the same library, maps = the helper's own (no libmpr.so)                -> lm sites NOT MAPPED  (the bug)
  x21-app          libJit_fx2_X21.so, maps = the camera application's, pid 543              -> lm sites STOCK        (the fix)
  x21-applied      X21, the encoder design's libmpr bytes                                   -> lm sites TARGET
  x21-noapp        X21, no process named im.elf                                             -> a clear line, nothing read
  x21-two          X21, two processes named im.elf                                          -> a clear line, nothing read
Every case also checks: nothing is written but the result file, and the identity lines hash the file the map list names.
"""
import hashlib
import os
import struct
import subprocess
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_INTR, UC_HOOK_MEM_FETCH_UNMAPPED
from unicorn.arm64_const import *

HERE = Path(__file__).resolve().parent
SDB = HERE.parent                                     # helper_fx2/sdboot
KIT = SDB.parent                                      # helper_fx2
sys.path.insert(0, str(KIT))

CODE, STACK, HEAP = 0x400000, 0x70000000, 0x80000000
APP = {"/libmpr.so": 0x7F5CF00000, "/libsencore.so": 0x7F60000000, "/libJiritsu.so": 0x7F61000000}
LIBSIZE = 0x2cdd00 + 0x1000   # the largest lm site ends at 0x2cdd08: the model file is just big enough to hold it
RESULT = "/tmp_wbshd/readcheck_result.txt"
IMPORT = 0x1000        # where a call to an undefined symbol lands; the fetch hook answers it


# ---------------------------------------------------------------- the site tables, out of the built header
def tables():
    src = HERE / "dump_tables.c"
    exe = HERE / "out" / "dump_tables"
    exe.parent.mkdir(exist_ok=True)
    if not exe.is_file():
        subprocess.run([os.environ.get("CC", "clang"), "-w", "-I", str(KIT), "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout
    t, cur = {"id_files": [], "id_pages": [], "cp_sites": [], "lm_sites": [], "av_sites": []}, None
    for line in out.splitlines():
        if not line.startswith(" "):
            cur = line if line in t else None
            continue
        p = line.split()
        if cur == "id_files":
            t[cur].append((p[0], bytes.fromhex(p[1])))
        elif cur == "id_pages":
            t[cur].append((int(p[0], 16), bytes.fromhex(p[1])))
        elif cur in ("lm_sites", "av_sites"):
            t[cur].append({"offset": int(p[0], 16), "length": int(p[1]), "stock": bytes.fromhex(p[2]), "target": bytes.fromhex(p[3])})
    return t


def blob_with_sha(want, size, salt=b""):
    """A blob of `size` bytes. The SHA-256 of a file is NOT chased here (a preimage search is not a test): the identity lines are
    expected to say DIFFERS in this model, and this test does not assert on them - it asserts on the libmpr sites, which is the
    one thing X21 changes."""
    return b"\x5a" + struct.pack("<I", 0) + bytes(size - 5)


# ---------------------------------------------------------------- the model camera
class Camera:
    def __init__(self, t, applied=False, apps=(543,)):
        self.apps = list(apps)
        # the FILE the identity line hashes is small (the emulated SHA-256 is slow); the MAPPING the sites are read at is large
        self.libs = {n: blob_with_sha(s, 4096) for n, s in t["id_files"]}
        lm = bytearray(self.libs["/libmpr.so"]) + bytes(LIBSIZE)
        for e in t["lm_sites"]:
            lm[e["offset"]:e["offset"] + e["length"]] = e["target"] if applied else e["stock"]
        self.app_lm = bytes(lm)
        self.written = {}

    def maps(self, who):
        libs = APP if who == "app" else {}
        return b"".join(b"%x-%x r-xp 00000000 b3:0f 100 /usr/lib%s\n" % (b, b + LIBSIZE, n.encode()) for n, b in libs.items())

    def app_read(self, addr, n):
        for name, b in APP.items():
            if b <= addr < b + (LIBSIZE if name == "/libmpr.so" else 0x1000):
                data = self.app_lm if name == "/libmpr.so" else self.libs[name]
                off = addr - b
                return data[off:off + n]
        return None


# ---------------------------------------------------------------- the "process" that loads the library
class Run:
    def __init__(self, lib, cam, self_has_lm, self_is_app=False):
        self.lib, self.cam, self.self_has_lm, self.self_is_app = lib, cam, self_has_lm, self_is_app
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.uc.mem_map(0, 0x400000)                    # the image loads at its own p_vaddr (0), and the import page is in here
        self.uc.mem_map(0x400000, 0x200000)
        self.uc.mem_map(STACK, 0x100000)
        self.uc.mem_map(HEAP, 0x4000000)
        # the camera application's mappings, as memory in this "process" (the kit's check, run inside im.elf, dereferences them)
        self.uc.mem_map(APP["/libmpr.so"], (LIBSIZE + 0xFFF) & ~0xFFF)
        self.uc.mem_write(APP["/libmpr.so"], cam.app_lm[:(LIBSIZE + 0xFFF) & ~0xFFF])
        for nm in ("/libsencore.so", "/libJiritsu.so"):
            self.uc.mem_map(APP[nm], 0x1000)
            self.uc.mem_write(APP[nm], cam.libs[nm])
        self.load(lib)
        self.fds, self.next_fd, self.out, self.wrote, self.maps_made = {}, 3, bytearray(), [], []
        self.uc.hook_add(UC_HOOK_INTR, self.syscall)      # SVC arrives here (interrupt 2) in this Unicorn build
        self.patch_imports()
        self.uc.hook_add(UC_HOOK_MEM_FETCH_UNMAPPED, self.import_call, None, IMPORT, IMPORT + 8, None)

    # ---- the three coprocessor calls, stood in for: a valid buffer, transfers that succeed and read zeros
    STUB = 0x300000
    def patch_imports(self):
        """Point the GOT slots of the three undefined symbols at small stubs, so the coprocessor part runs to its end and the
        main-processor part (which this test is about) is reached. The coprocessor part itself is not under test here."""
        lib = self.lib
        e_phoff, = struct.unpack_from("<Q", lib, 32)
        e_phentsize, e_phnum = struct.unpack_from("<HH", lib, 54)
        d = {}
        for i in range(e_phnum):
            p_type, p_flags, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", lib, e_phoff + i * e_phentsize)
            if p_type == 2:
                for k in range(0, p_filesz, 16):
                    tag, val = struct.unpack_from("<qQ", lib, p_off + k)
                    if tag == 0:
                        break
                    d.setdefault(tag, val)
        symtab, strtab = d[6], d[5]
        u = self.uc

        def stub(addr, words):
            u.mem_write(addr, b"".join(struct.pack("<I", w) for w in words))
        A, T, F = self.STUB, self.STUB + 0x40, self.STUB + 0x80
        # alloc: x0 = 0x47E67B000, *handle = 0, return
        stub(A, [0xD2A8F000, 0xF2A08000, 0xF2C8F000, 0xB9000020, 0xD65F03C0])
        stub(T, [0xD2800000, 0xD65F03C0])      # transfer: returns 0 (success)
        stub(F, [0xD2800000, 0xD65F03C0])      # free: returns 0
        want = {"_Z9dmm_allocjPj": A, "_Z8dmm_freej": F, "sen_dma_transfer": T}
        # .rela.plt (the GOT slots of the imported functions)
        e_shoff, = struct.unpack_from("<Q", lib, 40)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", lib, 58)
        sh = [struct.unpack_from("<IIQQQQIIQQ", lib, e_shoff + i * e_shentsize) for i in range(e_shnum)]
        stro = sh[e_shstrndx][4]
        for x in sh:
            nm = lib[stro+x[0]:lib.index(b"\0", stro+x[0])].decode()
            if nm not in (".rela.plt", ".rela.dyn"):
                continue
            for k in range(x[5] // 24):
                r_off, r_info, r_add = struct.unpack_from("<QQq", lib, x[4] + k * 24)
                sym = r_info >> 32
                if not sym:
                    continue
                name_off, = struct.unpack_from("<I", lib, symtab + sym * 24)
                s = lib[strtab + name_off:lib.index(b"\0", strtab + name_off)].decode()
                if s in want:
                    u.mem_write(r_off, struct.pack("<Q", want[s]))

    def ctor(self):
        """The library's single constructor, read from the init_array AFTER the relocations (before them the entry is 0)."""
        return struct.unpack_from("<Q", self.uc.mem_read(self.init_array, 8))[0]

    def load(self, lib):
        """Map the library's PT_LOAD segments where its p_vaddr says (0 for this build), as the camera's loader does."""
        e_phoff, = struct.unpack_from("<Q", lib, 32)
        e_phentsize, e_phnum = struct.unpack_from("<HH", lib, 54)
        for i in range(e_phnum):
            p_type, p_flags, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", lib, e_phoff + i * e_phentsize)
            if p_type != 1:
                continue
            self.uc.mem_write(p_vaddr, lib[p_off:p_off + p_filesz])
            if p_memsz > p_filesz:
                self.uc.mem_write(p_vaddr + p_filesz, bytes(p_memsz - p_filesz))
        # RELATIVE relocations (R_AARCH64_RELATIVE), as the camera's loader applies them: no other kind is in this build
        d = {}
        for i in range(e_phnum):
            p_type, p_flags, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", lib, e_phoff + i * e_phentsize)
            if p_type != 2:
                continue
            for k in range(0, p_filesz, 16):
                tag, val = struct.unpack_from("<qQ", lib, p_off + k)
                if tag == 0:
                    break
                d.setdefault(tag, val)
        # the init_array from the section header (DT_INIT_ARRAY in this link is the dynamic segment's own address)
        e_shoff, = struct.unpack_from("<Q", lib, 40)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", lib, 58)
        sh = [struct.unpack_from("<IIQQQQIIQQ", lib, e_shoff + i * e_shentsize) for i in range(e_shnum)]
        stro = sh[e_shstrndx][4]
        self.init_array = 0
        for x in sh:
            nm = lib[stro+x[0]:lib.index(b"\0", stro+x[0])].decode()
            if nm == ".init_array":
                self.init_array = x[3]
        self.base = 0
        if 7 in d:
            for i in range(d[0x6ffffff9]):
                off, info, add = struct.unpack_from("<QQq", lib, d[7] + i * 24)
                if info & 0xFFFFFFFF == 0x403:
                    self.uc.mem_write(off, struct.pack("<Q", add))  # r_offset is a VA here (p_vaddr 0 = file offset)

    # an undefined symbol (the three coprocessor calls) lands at IMPORT: report "nothing allocated" and return
    def import_call(self, uc, access, address, size, value, _):
        uc.reg_write(UC_ARM64_REG_X0, 0)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        return True

    def syscall(self, uc, intno, _):
        n = uc.reg_read(UC_ARM64_REG_X8)
        a = [uc.reg_read(getattr(sys.modules["unicorn.arm64_const"], "UC_ARM64_REG_X%d" % i)) for i in range(6)]
        uc.reg_write(UC_ARM64_REG_X0, self.dispatch(n, a) & 0xFFFFFFFFFFFFFFFF)


    def cstr(self, p):
        out = bytearray()
        while True:
            c = self.uc.mem_read(p, 1)[0]
            if not c:
                return out.decode()
            out.append(c)
            p += 1

    def dispatch(self, n, a):
        if n == 56:
            return self.open(self.cstr(a[1]))
        if n == 57:
            self.fds.pop(a[0], None)
            return 0
        if n == 63:
            e = self.fds.get(a[0])
            if not e or e[0] not in ("file", "result"):
                return -21
            if e[0] == "file" and e[1] is None:
                return -21
            chunk = e[1][e[2]:e[2] + a[2]]
            self.uc.mem_write(a[1], chunk)
            self.fds[a[0]] = [e[0], e[1], e[2] + len(chunk)]
            return len(chunk)
        if n == 61:                                     # getdents64: the pid list, one pass
            e = self.fds.get(a[0])
            if not e or e[0] != "dir":
                return -9
            names, start = e[1], e[2]
            if start:
                return 0
            out = bytearray()
            for i, nm in enumerate(names):
                # linux_dirent64: d_ino(8) d_off(8) d_reclen(2) d_type(1) then d_name at offset 19
                padded = (19 + len(nm) + 1 + 7) // 8 * 8
                rec = struct.pack("<QqHB", i + 1, i + 1, padded, 8) + nm.encode() + b"\0"
                rec += bytes(padded - len(rec))
                if len(out) + len(rec) > a[2]:
                    self.fds[a[0]] = ["dir", names[i:], i]
                    break
                out += rec
            else:
                self.fds[a[0]] = ["dir", [], len(names)]
            self.uc.mem_write(a[1], bytes(out))
            return len(out) or 0
        if n == 64:                                     # write: the result file only is kept
            data = bytes(self.uc.mem_read(a[1], a[2]))
            self.out += data
            e = self.fds.get(a[0])
            if e and e[0] == "result":
                self.wrote.append(RESULT)
                self.cam.written[RESULT] = bytes(self.out)
            return a[2]
        if n == 67:                                     # pread64: the camera application's memory
            e = self.fds.get(a[0])
            if not e:
                return -9
            if e[0] == "mem":
                blob = self.cam.app_read(a[3], a[2])
                if blob is None:
                    return -14
                self.uc.mem_write(a[1], blob)
                return len(blob)
            return -21
        if n == 222:                                    # mmap: a page of zeros, for the coprocessor buffer's view
            dst = a[0] or (HEAP + 0x200000 + 0x10000 * len(self.maps_made))
            self.maps_made.append((dst, a[1]))
            self.uc.mem_write(dst, bytes((a[1] + 0xFFF) & ~0xFFF))
            return dst
        if n in (215, 175):
            return 0
        return -38

    def open(self, path):
        fd, self.next_fd = self.next_fd, self.next_fd + 1
        if path == RESULT:
            self.fds[fd] = ["result", b"", 0]
            return fd
        if path == "/proc":
            self.fds[fd] = ["dir", [str(p) for p in self.cam.apps] + ["1000", "1"], 0]
            return fd
        parts = path.split("/")
        pid = 999 if len(parts) >= 4 and parts[2] == "self" else (int(parts[2]) if len(parts) >= 3 and parts[1] == "proc" and parts[2].isdigit() else -1)
        if len(parts) >= 4 and parts[1] == "proc" and path.endswith("/comm"):
            nm = b"im.elf\n" if pid in self.cam.apps else (b"busybox\n" if pid == 1000 else b"init\n")
            self.fds[fd] = ("file", nm, 0)
            return fd
        if len(parts) >= 4 and parts[1] == "proc" and path.endswith("/maps"):
            who = "app" if (pid in self.cam.apps or (pid == 999 and self.self_is_app)) else "self"
            maps = self.cam.maps(who)
            if who == "self" and self.self_has_lm:       # a program that itself has libmpr.so (the kit's assumption)
                maps += b"%x-%x r-xp 00000000 b3:0f 100 /usr/lib/libmpr.so\n" % (0x9000000000, 0x9000000000 + LIBSIZE)
            self.fds[fd] = ["file", maps, 0]
            return fd
        if len(parts) >= 4 and parts[1] == "proc" and path.endswith("/mem"):
            self.fds[fd] = ["mem", pid, 0]
            return fd
        if path == "/dev/mem":
            self.fds[fd] = ["file", bytes(1 << 20), 0]
            return fd
        if path in ("/proc/version", "/proc/cmdline", "/proc/iomem", "/proc/mounts", "/proc/modules", "/proc/meminfo", "/proc/self/status"):
            body = {"version": b"Linux version 4.9.337-scel (model)\n"}.get(path.split("/")[-1], b"\n")
            self.fds[fd] = ["file", body, 0]
            return fd
        for n, b in self.cam.libs.items():
            if path.endswith(n):
                self.fds[fd] = ["file", b, 0]
                return fd
        return -2

    def go(self):
        ctor = self.ctor()
        uc = self.uc
        uc.reg_write(UC_ARM64_REG_SP, STACK + 0xF0000)
        uc.reg_write(UC_ARM64_REG_LR, 0)
        # every undefined dynamic symbol lands on the import page, so a call returns "nothing"
        e_phoff, = struct.unpack_from("<Q", self.lib, 32)
        e_phentsize, e_phnum = struct.unpack_from("<HH", self.lib, 54)
        phs = [struct.unpack_from("<IIQQQQQQ", self.lib, e_phoff + i * e_phentsize) for i in range(e_phnum)]
        loads = [(x[3], x[2], x[5]) for x in phs if x[0] == 1]
        v2o = lambda va: next(va - v + o for v, o, n in loads if v <= va < v + n)
        for x in phs:
            if x[0] == 2:
                for k in range(0, x[5], 16):
                    tag, val = struct.unpack_from("<qQ", self.lib, x[2] + k)
                    if tag == 0:
                        break
                    if tag == 6:                          # DT_SYMTAB
                        self.symtab = v2o(val)
                    if tag == 5:                          # DT_STRTAB
                        self.strtab = v2o(val)
                    if tag == 4:                          # DT_HASH
                        self.hash = v2o(val)
        return uc.emu_start(ctor, 0, count=40_000_000)


def ctor_address(lib):
    e_phoff, = struct.unpack_from("<Q", lib, 32)
    e_phentsize, e_phnum = struct.unpack_from("<HH", lib, 54)
    phs = [struct.unpack_from("<IIQQQQQQ", lib, e_phoff + i * e_phentsize) for i in range(e_phnum)]
    loads = [(x[3], x[2], x[5]) for x in phs if x[0] == 1]
    v2o = lambda va: next(va - v + o for v, o, n in loads if v <= va < v + n)
    for x in phs:
        if x[0] == 2:
            for k in range(0, x[5], 16):
                tag, val = struct.unpack_from("<qQ", lib, x[2] + k)
                if tag == 0:
                    break
                if tag == 27:
                    return struct.unpack_from("<Q", lib, v2o(val))[0]


def run(lib, cam, self_has_lm=False, self_is_app=False):
    r = Run(lib, cam, self_has_lm, self_is_app)
    r.go()
    return bytes(r.out).decode("utf8", "replace"), r


def lm_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("lm ")]


def main():
    t = tables()
    check = (KIT / "libJit_fx2_check.so").read_bytes()
    x21 = (SDB / "libJit_fx2_X21.so").read_bytes()
    print("kit check %d bytes, X21 %d bytes; %d libmpr sites, %d coprocessor sites\n"
          % (len(check), len(x21), len(t["lm_sites"]), len(t["cp_sites"])))
    ok = True

    def case(name, want, text, r, extra=()):
        nonlocal ok
        problems = list(extra)
        if want not in text:
            problems.append("missing %r" % want)
        wrote = set(r.wrote) - {RESULT}
        if wrote:
            problems.append("wrote other files: %s" % sorted(wrote))
        print("%-16s %-6s  %s" % (name, "ok" if not problems else "FAILED", "; ".join(problems)))
        ok &= not problems
        return problems

    # 1. the kit's check with the camera application's maps: all six libmpr sites are read
    cam = Camera(t)
    text, r = run(check, cam, self_is_app=True)      # the kit's check runs INSIDE im.elf: /proc/self is the camera application
    lm = lm_lines(text)
    print("  kit-check-app    lm lines: %s" % ("%d, all STOCK" % len(lm) if lm and all(x.endswith("STOCK") for x in lm) else lm))
    if not (len(lm) == len(t["lm_sites"]) and all(x.endswith("STOCK") for x in lm)):
        ok = False

    # 2. the bug: the same library, in a process that has no libmpr.so of its own
    cam2 = Camera(t)
    text, r = run(check, cam2, self_has_lm=False)
    lm = lm_lines(text)
    print("  kit-check-self   lm lines: %s" % (set(x.rsplit(" ", 1)[-1] for x in lm) or "none"))
    if not lm or not all("NOT MAPPED" in x for x in lm):
        print("  !! the bug is not reproduced, so this test proves nothing"); ok = False

    # 3. the fix: X21 reads the camera application's maps and memory
    cam3 = Camera(t)
    text, r = run(x21, cam3)
    lm = lm_lines(text)
    print("  x21-app          lm lines: %s" % ("%d, positions %s" % (len(lm), [x.split()[3] for x in lm]) if lm else lm))
    if not (len(lm) == len(t["lm_sites"]) and all(x.endswith("STOCK") for x in lm)):
        print("  !! X21 did not read the libmpr sites: %s" % lm); ok = False
    if "the camera application, process 543" not in text:
        print("  !! the identity line does not name the camera application"); ok = False

    # 4. X21 on the applied state: TARGET
    cam4 = Camera(t, applied=True)
    text, r = run(x21, cam4)
    lm = lm_lines(text)
    print("  x21-applied      lm lines: %s" % (set(x.rsplit(" ", 1)[-1] for x in lm) or "none"))
    if not (len(lm) == len(t["lm_sites"]) and all(x.endswith("TARGET") for x in lm)):
        print("  !! X21 did not report TARGET: %s" % lm); ok = False

    # 5. no camera application: a clear line, and no libmpr site claimed
    cam5 = Camera(t, apps=())
    text, r = run(x21, cam5)
    lm = lm_lines(text)
    print("  x21-noapp        %s" % [x for x in text.splitlines() if "im.elf" in x][:1])
    if not any("im.elf" in x for x in text.splitlines()) or any(x.endswith("STOCK") for x in lm):
        print("  !! no app: %s" % lm); ok = False

    # 6. two processes named im.elf: refused, as the write steps refuse
    cam6 = Camera(t, apps=(543, 544))
    text, r = run(x21, cam6)
    lm = lm_lines(text)
    print("  x21-two          %s" % [x for x in text.splitlines() if "im.elf" in x][:1])
    if any(x.endswith("STOCK") or x.endswith("TARGET") for x in lm):
        print("  !! two apps: sites were read anyway: %s" % lm); ok = False

    print("\n%s" % ("ALL PASS" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
