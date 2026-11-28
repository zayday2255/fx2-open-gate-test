"""Build the FX2 1.01 start-up loader ("sdboot") and its kit steps. Offline; nothing is sent anywhere. (2026-11-28)

  C:\\Python313\\python.exe -B build_fx2boot.py [--regen] [--regen-check]

What it makes, in this folder:
  fx2boot_mp_gen.c            the kit's level 18/19/20 (helper/readcheck.c) for a process OUTSIDE the camera application: readcheck.c with
                              the exact text changes listed in MP_EDITS below, each of which must match exactly once. It is written once and
                              kept (readcheck.c is shared with other kits and changes); --regen makes it again from today's readcheck.c.
  fx2boot_chk_gen.c           the kit's read-only check (../fx2read.c) for a process outside the camera application: CHK_EDITS, kept the same
                              way; --regen-check makes it again from today's fx2read.c
  libJit_fx2_X0               that source: the check the helper's plan `check` runs (coprocessor sites through fx2cp.so, the application's
                              files and libmpr.so through /proc)
  libJit_fx2_X18 / X19 / X20  fx2boot_mp_gen.c at level 18 (read-only), 19 (apply) and 20 (put back), with the encoder design of the kit's L19 / L20
  fx2cp.so                    fx2cp.c: the three coprocessor-transfer functions for a process of its own (soname libsencore.so)
  fx2boot_manifest.h          the build's name, the helper's files with size and SHA-256, the plans
  fx2hook.so                  fx2hook.c: the start-up hook (it holds the manifest)
  fx2boot_hookfile.h          the hook's own size and SHA-256, for the install step
  put/*.h, libJit_fx2_W<n>.so the kit steps: W1.. bring one piece of one file to the camera's RAM disk; W30 run now (RAM only); W40 install,
                              W41 uninstall, W42 status, W43 the last run's results in full; W50.. choose a plan (RAM); W58 / W59 off switch
  fx2boot_pins.json           every kit step with its file, SHA-256, size and one-line description (fx2_run.py holds the same pins)
The step libraries the helper runs (L13, H5, P5, L5, L16, S16) are the kit's own files from ..; their SHA-256 must be the kit's pins.
The compiler is the kit's (zig cc, work\\venv_zig), with the kit's flags.
"""
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent                                  # helper_fx2
HELPER = KIT.parent / "helper"
ROOT = KIT.parents[2]                              # a7iv_map, or the published tools folder
ZIG = [str(ROOT / "work/venv_zig/Scripts/python.exe"), "-m", "ziglang", "cc"]
DEV = ROOT / "work/extracted/fx2_101/0700_part_image/dev"
BUILD = "fx2boot_v2"                               # v2 (2026-11-28, after the first run on a camera, issue 16): the check for outside (X0), W43
LIMIT = 65520                                      # the largest library the service file-write command takes
CHUNK = 56000                                      # bytes of a file one carrier step holds
FLAGS = ["-target", "aarch64-linux-gnu", "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", "-nostdlib", "-ffreestanding",
         "-fno-stack-protector", "-fno-builtin", "-fno-asynchronous-unwind-tables", "-Wl,--no-undefined", "-Wl,-z,now", "-g0", "-s",
         "-Wl,-z,max-page-size=4096"]
MP_DESIGN_H = "expected_mp_ogfile2560_hs_s_fx2_v2.h"       # the kit's L19
KIT_STEPS = ("L13", "H5", "P5", "L5", "L16", "S16")   # the kit's own libraries the helper runs
PLANS = {"check": "X0 X18", "og2560": "L13 H5 L16 X19 S16", "og2560pal": "L13 P5 L16 X19 S16", "squeeze": "X20 L13 L5 S16"}     # as fx2boot.sh
PAYLOAD = ("fx2boot.sh", "fx2cp.so", "fx2hook.so", "libJit_fx2_X0.so", "libJit_fx2_X18.so", "libJit_fx2_L13.so", "libJit_fx2_H5.so",
           "libJit_fx2_P5.so", "libJit_fx2_L5.so", "libJit_fx2_L16.so", "libJit_fx2_X19.so", "libJit_fx2_X20.so", "libJit_fx2_S16.so")
CTL = (("W30", "MODE_RUN", None, "RAM only: start the start-up loader's helper once, now, from the RAM copy (the chosen plan); no flash is written"),
       ("W40", "MODE_INSTALL", None, "FLASH: install the start-up loader (copies its checked files to /etc/fx2boot and writes /etc/ld.so.preload)"),
       ("W41", "MODE_UNINSTALL", None, "FLASH: uninstall the start-up loader (removes /etc/ld.so.preload first, then /etc/fx2boot and earlier research builds' files)"),
       ("W42", "MODE_STATUS", None, "read-only: status of the start-up loader (what is installed, the plan, the helper's last report)"),
       ("W43", "MODE_REPORT", None, "read-only: the whole result of every step of the helper's last run, and its log (for the session folder)"),
       ("W50", "MODE_PLAN", "check", "RAM only: choose the helper's plan: check (read-only: reads the coprocessor and encoder sites from outside the camera application)"),
       ("W51", "MODE_PLAN", "og2560", "RAM only: choose the helper's plan: og2560 (the 3840x2560 open gate, 23.98p/24p: L13 H5 L16 X19 S16)"),
       ("W52", "MODE_PLAN", "og2560pal", "RAM only: choose the helper's plan: og2560pal (the 3840x2560 open gate on a PAL-set camera, 25p: L13 P5 L16 X19 S16)"),
       ("W53", "MODE_PLAN", "squeeze", "RAM only: choose the helper's plan: squeeze (the squeezed open gate: X20 L13 L5 S16)"),
       ("W58", "MODE_OFF", None, "FLASH (one empty file): switch the start-up hook off (/etc/fx2boot/off)"),
       ("W59", "MODE_ON", None, "FLASH: switch the start-up hook on again (removes /etc/fx2boot/off)"))

APP_HEAD = r'''/* ---- FX2 start-up loader, "outside" build (helper_fx2/sdboot/build_fx2boot.py). This library does NOT run inside the camera application: it
 * finds the one process named APP_COMM and reaches that process's MP_LIB through /proc/<pid>/maps and /proc/<pid>/mem, where the kit's level
 * reads /proc/self/maps and this process's own memory. The av-cam.bin part (physical memory) and every rule of the level are the kit's. */
'''
APP_FUNCS = r'''#define APP_COMM "im.elf"
static char app_maps[48], app_mem[48];
static i64 app_pid;
static int app_pm = -1;

/* `len` bytes of the camera application's memory at `addr`, through its memory file (pread64, number 67). */
__attribute__((noinline)) static int app_get(u64 addr, u8 *out, u32 len)
{
    return app_pm >= 0 && sc(67, app_pm, (i64)out, (i64)len, (i64)addr, 0, 0) == (i64)len;
}

static void app_path(char *dst, const char *pid, const char *tail)
{
    static const char head[] = TEST_ROOT "/proc/";
    u64 k = 0;
    for (u64 i = 0; head[i]; i++) dst[k++] = head[i];
    for (u64 i = 0; pid[i] && i < 11; i++) dst[k++] = pid[i];
    for (u64 i = 0; tail[i]; i++) dst[k++] = tail[i];
    dst[k] = 0;
}

/* 1 when exactly one process is named APP_COMM; app_pid, app_maps and app_mem are then set. */
static int app_find(void)
{
    static u8 d[4096];
    static char one[16];
    static const char want[] = APP_COMM;
    char p[48], c[24];
    int count = 0;
    i64 fd = sys_open(TEST_ROOT "/proc", 0x4000 /* O_RDONLY | O_DIRECTORY */, 0), n;
    if (fd < 0) return 0;
    while ((n = sc(NR_getdents64, fd, (i64)d, sizeof d, 0, 0, 0)) > 0)
        for (i64 q = 0; q < n; ) {
            const char *nm = (const char *)d + q + 19;
            u64 len = 0; int digits = 1;
            for (; nm[len]; len++) if (nm[len] < '0' || nm[len] > '9') digits = 0;
            if (digits && len > 0 && len < 12) {
                app_path(p, nm, "/comm");
                i64 cf = sys_open(p, F_RDONLY, 0);
                if (cf >= 0) {
                    i64 r = sys_read((int)cf, c, sizeof c - 1);
                    sys_close((int)cf);
                    if (r > 0 && c[r - 1] == '\n') r--;
                    int eq = r == (i64)(sizeof want - 1);
                    for (i64 k = 0; eq && k < r; k++) if (c[k] != want[k]) eq = 0;
                    if (eq) { if (!count) for (u64 k = 0; k <= len; k++) one[k] = nm[k]; count++; }
                }
            }
            q += *(const unsigned short *)(d + q + 16);
        }
    sys_close((int)fd);
    if (count != 1) return 0;
    app_pid = 0;
    for (u64 k = 0; one[k]; k++) app_pid = app_pid * 10 + (one[k] - '0');
    app_path(app_maps, one, "/maps");
    app_path(app_mem, one, "/mem");
    return 1;
}

'''
APP_LM18 = r'''#if LEVEL == 18
/* The MP_LIB table against the camera application's memory: each entry is read through the memory file, then judged as mp_check judges one. */
static int app_lm_check(u64 lo, u64 hi, struct mp_tally *y)
{
    int all = 1;
    i64 pm = sys_open(app_mem, F_RDONLY, 0);
    if (pm < 0) { puts_("!! the camera application's memory file could not be opened "); putnum(pm); puts_("\n"); return 0; }
    app_pm = (int)pm;
    const struct mp_site *e = mp_lm;
    for (u64 i = 0; i < sizeof mp_lm / sizeof mp_lm[0]; i++, e++) {
        u8 got[16];
        if (e->len > 16 || e->off + e->len > hi - lo || !app_get(lo + e->off, got, e->len)) {
            puts_("  lm entry "); mp_putx(e->off); puts_(" !! could not be read from the camera application's memory\n"); y->other++; all = 0; continue;
        }
        mp_check("lm", e, 1, got, e->off, e->len, y);
    }
    sys_close((int)pm);
    app_pm = -1;
    return all;
}
#endif

'''
APP_HELPERS = APP_HEAD + APP_FUNCS + APP_LM18          # the text fx2boot_mp_gen.c was generated with
MP_LINE ='/* One line of /proc/self/maps: "start-end perms offset dev inode path". Taken when the path ends with /MP_LIB and the offset is 0. */'
LM_PASS1 = r'''/* Pass 1 for the MP_LIB table of the camera application: each entry's bytes are read through its memory file, then judged by mp_pass1 as one
 * entry is (as mp_ld_pass1 does for the data segment). Nothing is written. */
__attribute__((noinline)) static int app_lm_pass1(u64 lo, u64 hi, u32 *n_todo)
{
    const struct mp_site *e = mp_lm;
    for (u64 i = 0; i < sizeof mp_lm / sizeof mp_lm[0]; i++, e++) {
        u8 got[16];
        mp_do_lm[i] = 0;
        if (e->len > 16 || e->off + e->len > hi - lo) return mp_refuse("lm", e, "lies outside the range that may be read");
        if (!app_get(lo + e->off, got, e->len)) return mp_refuse("lm", e, "cannot be read from the camera application's memory");
        if (!mp_pass1("lm", e, 1, &mp_do_lm[i], got, e->off, e->len, -1, n_todo)) return 0;
    }
    return 1;
}

'''
MP_RUN = "static void mp_run(volatile u8 *av, int fd, int pm, u64 lo, u64 hi)\n{"
# (old text, new text, how many times the old text must occur)
MP_EDITS = (
    (MP_LINE, APP_HELPERS + MP_LINE, 1),
    ('static int mp_find_lib(u64 *lo, u64 *hi, char *perms)\n{\n    static u8 buf[4096];\n    static char line[512];\n'
     '    u64 n = 0; int found = 0, over = 0;\n    i64 fd = sys_open(TEST_ROOT "/proc/self/maps", F_RDONLY, 0);',
     'static int mp_find_lib(u64 *lo, u64 *hi, char *perms)\n{\n    static u8 buf[4096];\n    static char line[512];\n'
     '    u64 n = 0; int found = 0, over = 0;\n    i64 fd = sys_open(app_maps, F_RDONLY, 0);                 /* outside build: the camera application\'s list */', 1),
    ('static int mp_lm_is(u64 lo, const struct mp_site *e, const u8 *bytes)\n{\n    const volatile u8 *mem = (const volatile u8 *)lo;\n'
     '    for (u32 k = 0; k < e->len; k++) if (mem[e->off + k] != bytes[k]) return 0;\n    return 1;\n}',
     'static int mp_lm_is(u64 lo, const struct mp_site *e, const u8 *bytes)\n{\n    u8 got[16];                                             /* outside build: read back through the memory file */\n'
     '    if (e->len > 16 || !app_get(lo + e->off, got, e->len)) return 0;\n    return mp_eq(got, bytes, e->len);\n}', 1),
    (MP_RUN, LM_PASS1 + MP_RUN, 1),
    ('    if (!mp_pass1("lm", mp_lm, n_lm, mp_do_lm, (const volatile u8 *)lo, 0, hi - lo, -1, &n_todo)) return;',
     '    if (!app_lm_pass1(lo, hi, &n_todo)) return;', 1),
    ('    if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in this process\'s list of mappings; nothing is written\\n");\n'
     '    else if (perms[0] != \'r\') puts_("!! the mapping of " MP_LIB " is not readable; nothing is written\\n");\n'
     '    else {\n'
     '        i64 pm = sys_open(TEST_ROOT "/proc/self/mem", F_RDWR, 0);\n'
     '        if (pm < 0) { puts_("!! /proc/self/mem open failed "); putnum(pm); puts_("; nothing is written\\n"); }\n'
     '        else {\n',
     '    if (!app_find()) puts_("!! the camera application (exactly one process named " APP_COMM ") was not found; nothing is written\\n");\n'
     '    else if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in the camera application\'s list of mappings; nothing is written\\n");\n'
     '    else if (perms[0] != \'r\') puts_("!! the mapping of " MP_LIB " is not readable; nothing is written\\n");\n'
     '    else {\n'
     '        i64 pm = sys_open(app_mem, F_RDWR, 0);\n'
     '        if (pm < 0) { puts_("!! the camera application\'s memory file could not be opened "); putnum(pm); puts_("; nothing is written\\n"); }\n'
     '        else {\n'
     '            app_pm = (int)pm;\n'
     '            puts_("outside build: the camera application is process "); putnum(app_pid); puts_("; its " MP_LIB " is reached through its memory file\\n");\n', 1),
    ('    if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in this process\'s list of mappings\\n");\n'
     '    else {\n',
     '    if (!app_find()) puts_("!! the camera application (exactly one process named " APP_COMM ") was not found\\n");\n'
     '    else if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in the camera application\'s list of mappings\\n");\n'
     '    else {\n'
     '        puts_("outside build: the camera application is process "); putnum(app_pid); puts_("\\n");\n', 1),
    ('        else { mp_check("lm", mp_lm, n_lm, (const u8 *)lo, 0, hi - lo, &lm); lm_read = 1; }     /* this process\'s own memory, inside that mapping only */',
     '        else lm_read = app_lm_check(lo, hi, &lm);                /* outside build: the camera application\'s memory, entry by entry */', 1),
)

# ---- X0: the kit's read-only check (../fx2read.c, the source of libJit_fx2_check.so) for a process OUTSIDE the camera application.
# The kit's check looks in its OWN process for three library files and for libmpr.so; beside the application those nine places are
# "not mapped" and its verdict is NOT READY whatever the camera holds (seen on the first camera run, issue 16). X0 reads the same tables
# with the same report lines, from the application's list of mappings and through its memory file. Coprocessor part: unchanged.
CHK_HEAD = r'''/* ---- FX2 start-up loader, "outside" build of the kit's read-only check (helper_fx2/sdboot/build_fx2boot.py). This library does NOT run
 * inside the camera application: it finds the one process named APP_COMM, takes that process's list of mappings (/proc/<pid>/maps) where the
 * kit's check takes /proc/self/maps, and reads that process's libmpr.so through /proc/<pid>/mem (opened read-only). The coprocessor part, the
 * av-cam.bin part, every table and every report line are the kit's. */
#define TEST_ROOT ""
'''
CHK_MAPS = "/* ------------------------------------------------------------------ /proc/self/maps and the kernel command line */"
CHK_EDITS = (
    (CHK_MAPS, CHK_HEAD + APP_FUNCS + CHK_MAPS, 1),
    (r'''    puts_("== identity: files of this process\n");''',
     r'''    puts_("== identity: files of the camera application\n");''', 1),
    (r'''        if (!path[0]) { puts_("  NOT MAPPED in this process\n"); n_other++; continue; }''',
     r'''        if (!path[0]) { puts_("  NOT MAPPED in the camera application\n"); n_other++; continue; }''', 1),
    (r'''    puts_("== main-processor sites: libmpr.so in this process\n");
    for (u64 i = 0; i < sizeof lm_sites / sizeof lm_sites[0]; i++) {''',
     r'''    puts_("== main-processor sites: libmpr.so in the camera application, through its memory file\n");
    if (app_pid) {
        i64 pm = sys_open(app_mem, F_RDONLY, 0);
        if (pm < 0) { puts_("!! the camera application's memory file could not be opened "); putnum(pm); puts_("\n"); }
        else app_pm = (int)pm;
    }
    for (u64 i = 0; i < sizeof lm_sites / sizeof lm_sites[0]; i++) {''', 1),
    (r'''        mp_report(e, (const u8 *)at);
    }''',
     r'''        u8 got[16];                                                  /* outside build: the bytes come through the memory file */
        if (e->length > sizeof got || !app_get(at, got, e->length)) { puts_("  NOT READ\n"); n_other++; continue; }
        mp_report(e, got);
    }
    if (app_pm >= 0) { sys_close(app_pm); app_pm = -1; }''', 1),
    (r'''puts_(" for ILME-FX2 1.01; read-only\n");''',
     r'''puts_(" for ILME-FX2 1.01; read-only\n");
    puts_("outside build " OUTSIDE_BUILD ": run in a process beside the camera application; that application's files and its libmpr.so are read through /proc\n");''', 1),
    (r'''    maps_len = read_all("/proc/self/maps", maps, sizeof maps);''',
     r'''    if (!app_find()) puts_("!! the camera application (exactly one process named " APP_COMM ") was not found: its files and its libmpr.so are not read\n");
    else { maps_len = read_all(app_maps, maps, sizeof maps); puts_("camera application: process "); putnum(app_pid); puts_("\n"); }''', 1),
    (r'''    puts_("== file /proc/self/maps\n"); put(maps, maps_len);''',
     r'''    puts_("== file "); puts_(app_pid ? app_maps : "/proc/(not found)/maps"); puts_("\n"); put(maps, maps_len);''', 1),
)


def generated(gen, src, edits, regen, what):
    """A kept, generated source: `src` with `edits` (each old text must occur exactly as often as stated). Made when absent or with --regen."""
    if not regen and gen.is_file():
        return
    text = src.read_bytes().decode("utf8").replace("\r\n", "\n")
    for old, new, count in edits:
        if text.count(old) != count:
            raise SystemExit("STOP: %s holds %d times (wanted %d) the text\n%s" % (src.name, text.count(old), count, old[:300]))
        text = text.replace(old, new)
    head = ("/* GENERATED by helper_fx2/sdboot/build_fx2boot.py from %s (SHA-256 %s). Do not edit.\n * It is %s with %d text changes: %s */\n"
            % (src.name, sha(src.read_bytes()), src.name, len(edits), what))
    gen.write_bytes((head + text).encode("utf8"))
    print("generated", gen.name)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def cc(args, out):
    r = subprocess.run(ZIG + args + ["-o", str(out)], capture_output=True, text=True, cwd=str(HERE))
    if r.returncode:
        raise SystemExit("STOP: the compiler failed for %s:\n%s\n%s" % (out.name, r.stdout[-3000:], r.stderr[-6000:]))
    for stray in (out.with_suffix(".lib"), out.with_suffix(".pdb")):
        stray.unlink(missing_ok=True)
    return out.read_bytes()


def elf_dyn(b):
    """DT_NEEDED names, soname, undefined and defined dynamic symbol names, init_array size."""
    e_phoff, = struct.unpack_from("<Q", b, 32)
    e_shoff, = struct.unpack_from("<Q", b, 40)
    e_phentsize, e_phnum, e_shentsize, e_shnum = struct.unpack_from("<HHHH", b, 54)
    phs = [struct.unpack_from("<IIQQQQQQ", b, e_phoff + i * e_phentsize) for i in range(e_phnum)]
    loads = [(p[3], p[2], p[5]) for p in phs if p[0] == 1]
    v2o = lambda va: next(va - v + o for v, o, n in loads if v <= va < v + n)
    dyn, needed = {}, []
    for p in phs:
        if p[0] == 2:
            for k in range(0, p[5], 16):
                tag, val = struct.unpack_from("<qQ", b, p[2] + k)
                if tag == 0:
                    break
                needed.append(val) if tag == 1 else dyn.setdefault(tag, val)
    st = v2o(dyn[5]) if 5 in dyn else None
    s = lambda o: b[st + o:b.index(b"\0", st + o)].decode()
    und, defd = [], []
    nsym = 0
    for i in range(e_shnum):
        sh = struct.unpack_from("<IIQQQQIIQQ", b, e_shoff + i * e_shentsize)
        if sh[1] == 11:
            nsym = sh[5] // 24
    if not nsym and 4 in dyn:
        nsym = struct.unpack_from("<I", b, v2o(dyn[4]) + 4)[0]
    if 6 in dyn:
        so = v2o(dyn[6])
        for i in range(1, nsym):
            name, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", b, so + i * 24)
            (und if shndx == 0 else defd).append(s(name))
    return {"needed": [s(o) for o in needed], "soname": s(dyn[14]) if 14 in dyn else None, "undefined": sorted(und), "defined": sorted(defd),
            "init_array": dyn.get(27, 0), "fini_array": dyn.get(28, 0)}


def check_freestanding(name, b, soname):
    d = elf_dyn(b)
    assert not d["needed"] and not d["undefined"], "%s needs %s / imports %s" % (name, d["needed"], d["undefined"])
    assert d["soname"] == soname and d["init_array"] == 8 and not d["fini_array"], "%s: soname %s, init_array %d" % (name, d["soname"], d["init_array"])
    assert len(b) <= LIMIT, "%s is %d bytes: over the %d the camera's file-write command takes" % (name, len(b), LIMIT)


def c_bytes(b):
    return ", ".join("0x%02x" % x for x in b)


def main():
    regen = "--regen" in sys.argv
    sys.path.insert(0, str(KIT.parent))
    import fx2_run                                                         # the kit's pins
    gen = HERE / "fx2boot_mp_gen.c"
    src = HELPER / "readcheck.c"
    if regen or not gen.is_file():
        text = src.read_bytes().decode("utf8").replace("\r\n", "\n")
        for old, new, count in MP_EDITS:
            if text.count(old) != count:
                raise SystemExit("STOP: readcheck.c holds %d times (wanted %d) the text\n%s" % (text.count(old), count, old[:300]))
            text = text.replace(old, new)
        head = ("/* GENERATED by helper_fx2/sdboot/build_fx2boot.py from helper/readcheck.c (SHA-256 %s). Do not edit.\n"
                " * It is readcheck.c with the %d text changes of MP_EDITS: levels 18 to 20 for a process OUTSIDE the camera application. */\n"
                % (sha(src.read_bytes()), len(MP_EDITS)))
        gen.write_bytes((head + text).encode("utf8"))
        print("generated", gen.name)
    pins = {}

    def pin(step, name, data, what):
        pins[step] = {"file": name, "sha256": sha(data), "size": len(data), "what": what}

    mp_flags = FLAGS + ["-Wl,-soname,libJit.so", "-I", str(HELPER), '-DMP_H="%s"' % MP_DESIGN_H, "-DAVCAM_PHYS=0x401000000UL"]
    x18 = cc(mp_flags + ["-DLEVEL=18", gen.name], HERE / "libJit_fx2_X18.so")
    x19 = cc(mp_flags + ["-DLEVEL=19", gen.name], HERE / "libJit_fx2_X19.so")
    x20 = cc(mp_flags + ["-DLEVEL=20", gen.name], HERE / "libJit_fx2_X20.so")
    for n, b in (("X18", x18), ("X19", x19), ("X20", x20)):
        check_freestanding(n, b, "libJit.so")
    pin("X18", "libJit_fx2_X18.so", x18, "the kit's level 18 for a process outside the camera application: reads the encoder-side sites of ogfile2560_hs_s_fx2_v2 (read-only)")
    pin("X19", "libJit_fx2_X19.so", x19, "the kit's level 19 for a process outside the camera application: applies the encoder-side design ogfile2560_hs_s_fx2_v2 (as L19)")

    pin("X20", "libJit_fx2_X20.so", x20, "the kit's level 20 for a process outside the camera application: puts back the encoder-side design ogfile2560_hs_s_fx2_v2 (as L20)")

    chk = HERE / "fx2boot_chk_gen.c"
    generated(chk, KIT / "fx2read.c", CHK_EDITS, regen or "--regen-check" in sys.argv, "the kit's read-only check for a process OUTSIDE the camera application (CHK_EDITS).")
    x0 = cc(FLAGS + ["-Wl,-soname,libJit.so", "-I", str(KIT), '-DOUTSIDE_BUILD="%s"' % BUILD, chk.name, str(DEV / "nflasha15/lib/libsencore.so")], HERE / "libJit_fx2_X0.so")
    d0 = elf_dyn(x0)
    assert d0["needed"] == ["libsencore.so"] and d0["soname"] == "libJit.so" and d0["init_array"] == 8 and not d0["fini_array"], d0
    assert d0["undefined"] == ["_Z8dmm_freej", "_Z9dmm_allocjPj", "sen_dma_transfer"], d0["undefined"]
    pin("X0", "libJit_fx2_X0.so", x0, "the kit's read-only check (fx2read) for a process outside the camera application: coprocessor sites through fx2cp.so, the application's files and libmpr.so through /proc")
    (HERE / "libJit_fx2_check.so").unlink(missing_ok=True)                 # build v1 carried the kit's check; v2 carries X0 in its place

    cp = cc(["-target", "aarch64-linux-gnu", "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", "-nostdlib", "-ffreestanding",
             "-fno-stack-protector", "-fno-builtin", "-fno-asynchronous-unwind-tables", "-Wl,--no-undefined", "-Wl,-z,now", "-g0", "-s",
             "-Wl,-z,max-page-size=4096", "-Wl,-soname,libsencore.so", "fx2cp.c", str(DEV / "nflasha15/lib/libosal_uipc.so"), str(DEV / "nflasha7/lib/libc-2.25.so")],
            HERE / "fx2cp.so")
    d = elf_dyn(cp)
    want_und = ["close", "ioctl", "open", "osal_dynamic_id", "osal_free_msg", "osal_rcv_msg_tmo", "osal_set_msg_src", "osal_snd_msg", "osal_snd_sync_msg",
                "osal_valloc_msg_wait", "write"]
    assert d["needed"] == ["libosal_uipc.so", "libc.so.6"] and d["soname"] == "libsencore.so", d
    assert d["undefined"] == want_und, d["undefined"]
    assert set(d["defined"]) >= {"_Z9dmm_allocjPj", "_Z8dmm_freej", "sen_dma_transfer"} and not d["init_array"], d
    # what the kit's step libraries import from libsencore.so must all be here
    for step in KIT_STEPS:
        b = (KIT / ("libJit_fx2_%s.so" % step)).read_bytes()
        assert sha(b) == fx2_run.PINS[step][1], "%s is not the kit's pinned file" % step
        k = elf_dyn(b)
        assert k["needed"] in ([], ["libsencore.so"]) and set(k["undefined"]) <= set(d["defined"]), (step, k["needed"], k["undefined"])
        (HERE / ("libJit_fx2_%s.so" % step)).write_bytes(b)               # the helper's copy: byte for byte the kit's

    files = [n for n in PAYLOAD if n != "fx2hook.so"]
    rows = []
    for n in files:
        b = (HERE / n).read_bytes()
        if n == "fx2boot.sh":
            assert b"\r" not in b, "fx2boot.sh must have LF line ends"
            for plan, steps in PLANS.items():
                assert ('    %s) STEPS="%s" ;;' % (plan, steps)).encode() in b, "fx2boot.sh and PLANS differ for %s" % plan
        assert len(n) < 40 and len(b) <= 256 * 1024
        rows.append('    { "%s", %d, { %s } },' % (n, len(b), c_bytes(hashlib.sha256(b).digest())))
    (HERE / "fx2boot_manifest.h").write_text(
        "/* GENERATED by build_fx2boot.py. The files of build %s that the helper uses, with size and SHA-256. Do not edit. */\n" % BUILD
        + '#define FX2BOOT_BUILD "%s"\n' % BUILD
        + "struct fx2boot_file { char name[40]; unsigned int size; unsigned char sha256[32]; };\n"
        + "static const struct fx2boot_file fx2boot_files[] = {\n" + "\n".join(rows) + "\n};\n"
        + "__attribute__((unused)) static const char fx2boot_plans[][16] = { %s };\n" % ", ".join('"%s"' % p for p in PLANS), encoding="utf8", newline="\n")
    hook = cc(FLAGS + ["-Wl,-soname,fx2hook.so", "fx2hook.c"], HERE / "fx2hook.so")
    check_freestanding("fx2hook.so", hook, "fx2hook.so")
    (HERE / "fx2boot_hookfile.h").write_text(
        "/* GENERATED by build_fx2boot.py. The start-up hook of build %s. Do not edit. */\n" % BUILD
        + 'static const struct fx2boot_file fx2boot_hook = { "fx2hook.so", %d, { %s } };\n' % (len(hook), c_bytes(hashlib.sha256(hook).digest())),
        encoding="utf8", newline="\n")

    put_dir = HERE / "put"
    put_dir.mkdir(exist_ok=True)
    for old in list(put_dir.glob("*.h")) + [p for p in HERE.glob("libJit_fx2_W*.so")]:
        old.unlink()
    step = 0
    order = []
    for n in PAYLOAD:
        b = (HERE / n).read_bytes()
        parts = [(o, b[o:o + CHUNK]) for o in range(0, len(b), CHUNK)]
        for k, (off, chunk) in enumerate(parts):
            step += 1
            name = "W%d" % step
            h = put_dir / ("put_%s.h" % name)
            h.write_text("/* GENERATED by build_fx2boot.py: %s, bytes %d to %d of %d. Do not edit. */\n" % (n, off, off + len(chunk), len(b))
                         + '#define PUT_NAME "%s"\n#define PUT_TOTAL %dUL\n#define PUT_OFFSET %dUL\n' % (n, len(b), off)
                         + "static const u8 put_bytes[%d] = { %s };\n" % (len(chunk), c_bytes(chunk)), encoding="utf8", newline="\n")
            lib = cc(FLAGS + ["-Wl,-soname,libJit.so", "-DLEVEL=%d" % step, '-DPUT_H="put/%s"' % h.name, "fx2boot_put.c"], HERE / ("libJit_fx2_%s.so" % name))
            check_freestanding(name, lib, "libJit.so")
            piece = "" if len(parts) == 1 else ", piece %d of %d" % (k + 1, len(parts))
            pin(name, "libJit_fx2_%s.so" % name, lib, "RAM only: bring %s (%d bytes%s) of the start-up loader to the camera's RAM disk" % (n, len(b), piece))
            order.append(name)
    assert step < 30
    for name, mode, plan, what in CTL:
        extra = ['-DPLAN_NAME="%s"' % plan] if plan else []
        lib = cc(FLAGS + ["-Wl,-soname,libJit.so", "-DLEVEL=%s" % name[1:], "-DMODE=%s" % mode] + extra + ["fx2boot_ctl.c"], HERE / ("libJit_fx2_%s.so" % name))
        check_freestanding(name, lib, "libJit.so")
        pin(name, "libJit_fx2_%s.so" % name, lib, what)
    out = {"build": BUILD, "readcheck_c_sha256_of_generated_source": gen.read_text(encoding="utf8").split("SHA-256 ")[1].split(")")[0],
           "fx2read_c_sha256_of_generated_source": chk.read_text(encoding="utf8").split("SHA-256 ")[1].split(")")[0],
           "stage_order": order, "plans": PLANS,
           "files": {n: {"sha256": sha((HERE / n).read_bytes()), "size": (HERE / n).stat().st_size} for n in PAYLOAD}, "steps": pins}
    (HERE / "fx2boot_pins.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    for k, v in pins.items():
        print("%-4s %s %6d  %s" % (k, v["sha256"], v["size"], v["file"]))
    print("payload:", ", ".join("%s %d" % (n, (HERE / n).stat().st_size) for n in PAYLOAD))
    print("stage order:", " ".join(order))
    return 0


if __name__ == "__main__":
    sys.exit(main())
