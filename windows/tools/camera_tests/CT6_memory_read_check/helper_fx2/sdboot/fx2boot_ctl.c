/*
 * fx2boot_ctl: the kit steps that manage the FX2 1.01 start-up loader (2026-11-28). One of these is built into each library (-DMODE=...):
 *
 *   MODE_STATUS     read-only. What is installed, what is on the RAM disk, whether each file is this build's, the chosen plan, and what the
 *                   helper wrote at the last power-on. Writes nothing but the kit's result file (RAM).
 *   MODE_RUN        RAM only. Checks the files on the RAM disk against the build's list, then starts the helper from there once, now, as a
 *                   process of its own, with the chosen plan. This is the test of the helper WITHOUT any start-up hook and without flash.
 *   MODE_PLAN       RAM only. Writes the plan's name (PLAN_NAME, a few bytes) to the RAM copy. The install step copies it to flash with the
 *                   files; an installed loader's plan is changed by bringing the files again, choosing, and installing again.
 *   MODE_OFF / _ON  makes / removes /etc/fx2boot/off: with it the start-up hook starts nothing. Flash, one empty file.
 *   MODE_INSTALL    FLASH. Copies the checked files from the RAM disk to /etc/fx2boot, checks each copy, and last of all writes
 *                   /etc/ld.so.preload (one line naming the hook). From then on the hook runs in every program the camera starts.
 *   MODE_UNINSTALL  FLASH. Removes /etc/ld.so.preload FIRST, then /etc/fx2boot and what earlier research builds left in /etc and /setting.
 *                   It needs none of the loader's files to be intact: it is the way back.
 *
 * /etc on this camera is the FAT partition nflasha10 (also mounted as /tmp and /var). A battery change does not undo a flash step; the
 * uninstall step does. A file is never changed in place: it is written under a second name, read back, and renamed.
 * No library is used and nothing is imported.
 */
#include "fx2boot_out.h"
#include "fx2boot_manifest.h"            /* FX2BOOT_BUILD, fx2boot_files[], fx2boot_plans[] */
#include "fx2boot_hookfile.h"            /* fx2boot_hook: the hook's own size and SHA-256 (it cannot list itself) */

#define MODE_STATUS 1
#define MODE_RUN 2
#define MODE_PLAN 3
#define MODE_OFF 4
#define MODE_ON 5
#define MODE_INSTALL 6
#define MODE_UNINSTALL 7
#ifndef MODE
#error "build with -DMODE=MODE_..."
#endif
#define MAX_FILE (256 * 1024)
#define NR_FILES (sizeof fx2boot_files / sizeof fx2boot_files[0])
#define NR_rt_sigprocmask 135
#define CLONE_VM 0x100
#define CLONE_VFORK 0x4000

#define MAYBE __attribute__((unused))     /* not every step uses every helper below */
MAYBE static u8 big[MAX_FILE];
static char path_a[200], path_b[200];

MAYBE static int known_plan(const u8 *b, i64 n)
{
    for (u64 i = 0; i < sizeof fx2boot_plans / sizeof fx2boot_plans[0]; i++)
        if (n == (i64)slen(fx2boot_plans[i]) && same(b, (const u8 *)fx2boot_plans[i], (u64)n)) return 1;
    return 0;
}

/* The plan file of a folder into `out` (at most 31 characters and a 0). 1: a known plan; 0: absent; -1: something else is in it. */
MAYBE static int plan_of(const char *dir, char *out)
{
    u8 b[40];
    out[0] = 0;
    if (!join(path_a, sizeof path_a, dir, "/plan")) return -1;
    i64 n = slurp(path_a, b, sizeof b);
    if (n == -1) return 0;
    if (n < 1 || n > 31 || !known_plan(b, n)) return -1;
    for (i64 i = 0; i < n; i++) out[i] = (char)b[i];
    out[n] = 0;
    return 1;
}

/* One file of a folder against the build's size and SHA-256. 1 as built, 0 absent, -1 different. */
MAYBE static int file_state(const char *dir, const struct fx2boot_file *f)
{
    u8 got[32];
    if (!join(path_a, sizeof path_a, dir, "/") || !join(path_b, sizeof path_b, path_a, f->name)) return -1;
    if (!sys_exists(path_b)) return 0;
    return sha_file(path_b, MAX_FILE, got) == (i64)f->size && same(got, f->sha256, 32) ? 1 : -1;
}

/* Every file of the build (and the hook) in a folder: prints one line per file when `list`; returns the number that are not as built. */
MAYBE static u64 folder_state(const char *dir, int list)
{
    u64 bad = 0;
    for (u64 i = 0; i <= NR_FILES; i++) {
        const struct fx2boot_file *f = i < NR_FILES ? &fx2boot_files[i] : &fx2boot_hook;
        int s = file_state(dir, f);
        if (s != 1) bad++;
        if (list) { put("  "); put(f->name); put(s == 1 ? ": this build's\n" : s == 0 ? ": absent\n" : ": NOT this build's file\n"); }
    }
    return bad;
}

MAYBE static u64 power_on_number(void)
{
    u8 b[32];
    u64 v = 0;
    i64 fd = sys_open("/sys/kernel/debug/suspend_stats", O_RDONLY, 0);
    if (fd < 0) return 0;
    i64 n = sys_read(fd, b, sizeof b);
    sys_close(fd);
    if (n < 10 || !same(b, (const u8 *)"success: ", 9)) return 0;
    for (i64 k = 9; k < n && b[k] >= '0' && b[k] <= '9'; k++) v = v * 10 + (u64)(b[k] - '0');
    return v;
}

/* What /etc/ld.so.preload holds: 0 absent, 1 this loader's line, 2 anything else (printed when `show`). */
MAYBE static int preload_state(int show)
{
    u8 b[256];
    i64 n = slurp(PRELOAD, b, sizeof b);
    if (n == -1) return 0;
    if (n == (i64)(sizeof PRELOAD_TEXT - 1) && same(b, (const u8 *)PRELOAD_TEXT, (u64)n)) return 1;
    if (show) { put("  it holds: "); puttext(b, n > 0 ? (u64)n : 0); put("\n"); }
    return 2;
}

#if MODE == MODE_STATUS || MODE == MODE_UNINSTALL
/* The names in a folder that `want` accepts (all, when it is 0), handed to `each` once the listing is closed, so `each` may remove them.
 * At most 64 names per pass; with `again` set the folder is listed anew while a pass was full (for removals: at most 16 passes).
 * Returns 0 when the folder cannot be read. */
static int for_names(const char *dir, int (*want)(const char *name), void (*each)(const char *dir, const char *name), int again)
{
    static u8 d[4096];
    static char names[64][64];
    for (int pass = 0; pass < 16; pass++) {
        u64 count = 0;
        i64 fd = sys_open(dir, O_RDONLY | O_DIRECTORY, 0), n;
        if (fd < 0) return pass > 0;
        while ((n = sc(NR_getdents64, fd, (i64)d, sizeof d, 0, 0, 0)) > 0)
            for (i64 p = 0; p < n; ) {
                const char *nm = (const char *)d + p + 19;
                u64 len = slen(nm);
                if (!(nm[0] == '.' && (nm[1] == 0 || (nm[1] == '.' && nm[2] == 0))) && len < 64 && count < 64 && (!want || want(nm))) {
                    for (u64 k = 0; k <= len; k++) names[count][k] = nm[k];
                    count++;
                }
                p += *(const unsigned short *)(d + p + 16);
            }
        sys_close(fd);
        for (u64 i = 0; i < count; i++) each(dir, names[i]);
        if (!again || count < 64) break;
    }
    return 1;
}
static int starts(const char *s, const char *with) { for (u64 i = 0; with[i]; i++) if (s[i] != with[i]) return 0; return 1; }
static int is_legacy(const char *name) { return starts(name, "fx2_") || starts(name, "fx2in_"); }      /* what earlier research builds left in /etc */
#endif

#if MODE == MODE_STATUS
static int is_ours(const char *name) { return starts(name, "fx2boot"); }
static int is_report(const char *name) { return starts(name, "fx2boot_"); }
static void list_name(const char *dir, const char *name) { (void)dir; put("  "); put(name); put("\n"); }
static void legacy_name(const char *dir, const char *name) { put("  left by an earlier research build: "); put(dir); put("/"); put(name); put("\n"); }
/* The outcome lines of one saved step result. */
static void outcome_of(const char *dir, const char *name)
{
    if (!join(path_a, sizeof path_a, dir, "/") || !join(path_b, sizeof path_b, path_a, name)) return;
    i64 n = slurp(path_b, big, sizeof big);
    if (n <= 0) return;
    put("  "); put(name); put(":\n");
    for (i64 a = 0; a < n; ) {
        i64 e = a;
        while (e < n && big[e] != '\n') e++;
        const char *l = (const char *)big + a;
        u64 len = (u64)(e - a);
        /* The outcome lines of one saved step result. A read-only step's outcome is its VERDICT line (X21, or the kit's own check):
         * without it the entry was printed with nothing under it. "other " and "lm " carry the bytes a read step reports. */
        if ((len > 5 && (starts(l, "DONE") || starts(l, "NOTHING") || starts(l, "NOT DONE") || starts(l, "VERDICT") || starts(l, "!!")
                         || starts(l, "UNDO") || starts(l, "== level") || starts(l, "lm ") || starts(l, "other ")))) {
            put("    "); puttext(big + a, len > 300 ? 300 : len); put("\n");
        }
        a = e + 1;
    }
}

static void run(void)
{
    char plan[32];
    if (!out_begin("status of the start-up loader, build " FX2BOOT_BUILD "; read-only")) return;
    put("power-on number (completed suspends; 0 = cold boot or not readable): "); putn((i64)power_on_number()); put("\n");
    int p = preload_state(0);
    put(PRELOAD ": "); put(p == 0 ? "absent (as the firmware ships it)\n" : p == 1 ? "this loader's line: the start-up hook is INSTALLED\n" : "holds something that is not this loader's line\n");
    if (p == 2) preload_state(1);
    put("installed copy, " FLASH ":");
    if (!sys_exists(FLASH)) put(" absent\n");
    else {
        put("\n");
        u64 bad = folder_state(FLASH, 1);
        int s = plan_of(FLASH, plan);
        put("  plan: "); put(s == 1 ? plan : s == 0 ? "none (the helper does nothing)" : "NOT a known plan (the helper does nothing)"); put("\n");
        put("  off switch (" FLASH "/off): "); put(sys_exists(FLASH "/off") ? "SET: the hook starts nothing\n" : "not set\n");
        put(bad ? "  => the installed copy is NOT complete: the hook starts nothing\n" : "  => every file is this build's\n");
    }
    put("RAM copy, " STAGE ":");
    if (!sys_exists(STAGE)) put(" absent\n");
    else {
        put("\n");
        u64 bad = folder_state(STAGE, 1);
        int s = plan_of(STAGE, plan);
        put("  plan: "); put(s == 1 ? plan : s == 0 ? "none" : "NOT a known plan"); put("\n");
        put(bad ? "  => not complete\n" : "  => every file is this build's\n");
    }
    put("names in /etc left by earlier research builds (the uninstall step removes them):\n");
    if (!for_names("/etc", is_legacy, legacy_name, 0)) put("  (the folder could not be listed)\n");
    put("the helper's reports of its last run (RAM):\n");
    for_names("/tmp_wbshd", is_report, outcome_of, 0);
    put("the helper's log (RAM, the last 6000 characters):\n");
    i64 n = slurp(RUN_LOG, big, sizeof big);
    if (n == -1) put("  (none: the helper has not run since the battery was last out)\n");
    else if (n >= 0) puttext(big + (n > 6000 ? n - 6000 : 0), (u64)(n > 6000 ? 6000 : n));
    put("the loader's names on the RAM disk:\n");
    for_names("/tmp_wbshd", is_ours, list_name, 0);
    put("DONE: status read; nothing was written\n");
    out_end();
}
#endif

#if MODE == MODE_RUN
#define BUSY "/tmp_wbshd/fx2boot.busy"
/* The first shell only starts the helper script in the background and ends, so the camera application is left with no child of ours. */
#define SHELL_LINE "/bin/busybox sh " STAGE "/fx2boot.sh " STAGE " usb " FX2BOOT_BUILD " now </dev/null >/dev/null 2>&1 &"
/* In the child of a vfork-like clone: it shares this process's memory until it runs another program, so it touches nothing but its own
 * descriptors and signal mask, and ends by running the camera's shell (or by ending itself). */
__attribute__((noinline, noreturn)) static void child(void)
{
    static const u64 none = 0;
    static const char *const argv[] = { "busybox", "sh", "-c", SHELL_LINE, 0 };
    static const char *const envp[] = { "PATH=/sbin:/bin:/usr/sbin:/usr/bin", "HOME=/", 0 };
    for (int fd = 0; fd < 1024; fd++) sys_close(fd);
    if (sys_open("/dev/null", O_RDWR, 0) == 0) { sc(NR_dup3, 0, 1, 0, 0, 0, 0); sc(NR_dup3, 0, 2, 0, 0, 0, 0); }
    sc(NR_rt_sigprocmask, 2 /* SIG_SETMASK */, (i64)&none, 0, 8, 0, 0);
    sc(NR_setsid, 0, 0, 0, 0, 0, 0);
    sc(NR_execve, (i64)"/bin/busybox", (i64)argv, (i64)envp, 0, 0, 0);
    sc(NR_exit_group, 127, 0, 0, 0, 0, 0);
    for (;;) { }
}

static void run(void)
{
    char plan[32];
    if (!out_begin("start the helper once, now, from the RAM copy (" STAGE "), build " FX2BOOT_BUILD "; no flash is written")) return;
    u64 bad = folder_state(STAGE, 1);
    int s = plan_of(STAGE, plan);
    if (bad) put("!! the RAM copy is not complete (send the loader's files first); nothing is written and nothing is started\n");
    else if (s != 1) put("!! no known plan is chosen on the RAM disk (run a plan step first); nothing is written and nothing is started\n");
    else {
        if (sys_exists(BUSY)) put("note: " BUSY " is there: a helper may still be at work; the new one then ends at once and says so in its log\n");
        i64 pid = sc(NR_clone, CLONE_VM | CLONE_VFORK | SIGCHLD, 0, 0, 0, 0, 0);
        if (pid == 0) child();
        if (pid < 0) { put("NOT DONE: the helper could not be started ("); putn(pid); put(")\n"); }
        else {
            int status = -1;
            i64 w = sc(NR_wait4, pid, (i64)&status, 0, 0, 0, 0);
            put("DONE: the helper was started from the RAM copy with plan "); put(plan);
            put(" (starter "); putn(pid); put(", wait "); putn(w); put(", status "); putn(status);
            put("). It works on its own now: read what it did with the status step in half a minute\n");
        }
    }
    out_end();
}
#endif

/* `n` bytes into a new file `to` by way of `to`.new: written, synced, read back and compared, then renamed. 1 on success. */
__attribute__((unused)) static int place(const char *to, const u8 *bytes, u64 n, int mode)
{
    static u8 back[MAX_FILE];
    static char tmp[200];
    if (!join(tmp, sizeof tmp, to, ".new")) return 0;
    i64 fd = sys_open(tmp, O_WRONLY | O_CREAT | O_TRUNC, mode);
    if (fd < 0) return 0;
    i64 w = n ? sys_write(fd, bytes, n) : 0;
    sc(NR_fsync, fd, 0, 0, 0, 0, 0);
    sys_close(fd);
    if (w != (i64)n || slurp(tmp, back, sizeof back) != (i64)n || !same(back, bytes, n)) { sys_unlink(tmp); return 0; }
    if (sc(NR_renameat, AT_FDCWD, (i64)tmp, AT_FDCWD, (i64)to, 0, 0) < 0) { sys_unlink(tmp); return 0; }
    return 1;
}

#if MODE == MODE_PLAN
static void run(void)
{
    static const char name[] = PLAN_NAME;
    if (!out_begin("choose the plan " PLAN_NAME " for the start-up loader's helper, on the RAM copy; no flash is written")) return;
    if (!known_plan((const u8 *)name, (i64)(sizeof name - 1))) put("!! " PLAN_NAME " is not a plan of this build; nothing is written\n");
    else if (!sys_exists(STAGE)) put("!! there is no RAM copy of the loader (send its files first); nothing is written\n");
    else if (place(STAGE "/plan", (const u8 *)name, sizeof name - 1, 0600))
        put("DONE: the RAM copy's plan is " PLAN_NAME " (written and read back); the install step copies it to flash with the files\n");
    else put("NOT DONE: the plan file could not be written\n");
    out_end();
}
#endif

#if MODE == MODE_OFF || MODE == MODE_ON
static void run(void)
{
    if (!out_begin(MODE == MODE_OFF ? "switch the start-up hook off (" FLASH "/off)" : "switch the start-up hook on again (remove " FLASH "/off)")) return;
    if (!sys_exists(FLASH)) put("!! the loader is not installed (" FLASH " is absent); nothing is written\n");
#if MODE == MODE_OFF
    else if (sys_exists(FLASH "/off")) put("NOTHING TO DO: the off switch is already set\n");
    else if (place(FLASH "/off", (const u8 *)"", 0, 0600) && sys_exists(FLASH "/off")) put("DONE: the off switch is set: the hook starts nothing until it is removed\n");
    else put("NOT DONE: the off switch could not be made\n");
#else
    else if (!sys_exists(FLASH "/off")) put("NOTHING TO DO: the off switch is not set\n");
    else { sys_unlink(FLASH "/off"); put(sys_exists(FLASH "/off") ? "NOT DONE: the off switch could not be removed\n" : "DONE: the off switch is removed\n"); }
#endif
    out_end();
}
#endif

#if MODE == MODE_INSTALL
static int copy_one(const struct fx2boot_file *f)
{
    u8 got[32];
    if (!join(path_a, sizeof path_a, STAGE "/", f->name)) return 0;
    i64 n = slurp(path_a, big, sizeof big);
    if (n != (i64)f->size) return 0;
    static char to[200];
    if (!join(to, sizeof to, FLASH "/", f->name) || !place(to, big, (u64)n, 0700)) return 0;
    return sha_file(to, MAX_FILE, got) == (i64)f->size && same(got, f->sha256, 32);
}

static void run(void)
{
    char plan[32];
    if (!out_begin("INSTALL the start-up loader, build " FX2BOOT_BUILD ": copies to flash (" FLASH ") and writes " PRELOAD)) return;
    int p = preload_state(1);
    u64 bad = folder_state(STAGE, 1);
    int s = plan_of(STAGE, plan);
    if (bad) put("!! the RAM copy is not complete (send the loader's files first); nothing is written\n");
    else if (s != 1) put("!! no known plan is chosen on the RAM disk (run a plan step first); nothing is written\n");
    else if (p == 2) put("!! " PRELOAD " holds something that is not this loader's line (shown above): run the uninstall step first; nothing is written\n");
    else if (!power_on_number()) put("!! the kernel's count of suspends cannot be read or is 0: the hook would never start anything here; nothing is written\n");
    else {
        i64 r = sys_mkdir(FLASH, 0700);
        int ok = r == 0 || r == -EEXIST;
        if (!ok) { put("!! the folder " FLASH " could not be made ("); putn(r); put(")\n"); }
        for (u64 i = 0; ok && i <= NR_FILES; i++) {
            const struct fx2boot_file *f = i < NR_FILES ? &fx2boot_files[i] : &fx2boot_hook;
            ok = copy_one(f);
            put("  "); put(f->name); put(ok ? ": copied to flash, read back, SHA-256 as built\n" : ": !! the copy on flash is not as built\n");
        }
        if (ok) { ok = place(FLASH "/plan", (const u8 *)plan, slen(plan), 0600); put(ok ? "  plan: copied\n" : "  plan: !! could not be written\n"); }
        if (ok && folder_state(FLASH, 0)) { ok = 0; put("!! the installed copy does not check out as a whole\n"); }
        if (!ok) put(p == 1 ? "NOT DONE: the copy failed; " PRELOAD " was left as it was. Run the uninstall step, then start again\n"
                            : "NOT DONE: the copy failed; " PRELOAD " was not written, so nothing of this is used. Run the uninstall step, then start again\n");
        else if (p == 1) { put("DONE: the files of build " FX2BOOT_BUILD " are installed with plan "); put(plan); put("; " PRELOAD " already held this loader's line\n"); }
        else if (!place(PRELOAD, (const u8 *)PRELOAD_TEXT, sizeof PRELOAD_TEXT - 1, 0644) || preload_state(0) != 1)
            put("NOT DONE: " PRELOAD " could not be written; the files are on flash but nothing uses them. Run the uninstall step\n");
        else { put("DONE: the start-up loader is INSTALLED with plan "); put(plan); put(". It is on flash: only the uninstall step removes it\n"); }
    }
    out_end();
}
#endif

#if MODE == MODE_UNINSTALL
static void remove_in(const char *dir, const char *name)
{
    if (join(path_a, sizeof path_a, dir, "/") && join(path_b, sizeof path_b, path_a, name)) sys_unlink(path_b);
}
static void remove_legacy(const char *dir, const char *name) { remove_in(dir, name); put("  removed "); put(dir); put("/"); put(name); put("\n"); }
static int is_mark(const char *name) { return starts(name, "fx2boot.g") || starts(name, "fx2boot_") || streq(name, "fx2boot.busy"); }

static void run(void)
{
    if (!out_begin("UNINSTALL the start-up loader: removes " PRELOAD " first, then " FLASH " and what earlier research builds left")) return;
    int p = preload_state(1);
    put(PRELOAD ": "); put(p == 0 ? "was absent\n" : p == 1 ? "held this loader's line\n" : "held something else (shown above)\n");
    sys_unlink(PRELOAD);                                           /* first: from here on the camera's loader preloads nothing */
    sys_unlink(PRELOAD ".new");
    int listed = for_names(FLASH, 0, remove_in, 1);
    sys_rmdir(FLASH);
    put(FLASH ": "); put(listed ? "its files and the folder removed\n" : "was absent\n");
    for_names("/etc", is_legacy, remove_legacy, 1);                /* fx2_preload_marker.so, fx2_any, fx2_imelf, fx2in_<name>, fx2_preload_ran */
    static const char *const old[] = { "/setting/mode/preload", "/setting/fx2_preload_marker.so", "/setting/fx2_preload_ran" };
    for (u64 i = 0; i < sizeof old / sizeof old[0]; i++)
        if (sys_exists(old[i])) { sys_unlink(old[i]); put("  removed "); put(old[i]); put("\n"); }
    for_names(STAGE, 0, remove_in, 1);                             /* the RAM copy and the hook's marks: a later install starts clean */
    sys_rmdir(STAGE);
    for_names("/tmp_wbshd", is_mark, remove_in, 1);
    if (sys_exists(PRELOAD) || sys_exists(FLASH))
        put("NOT DONE: something could not be removed (" PRELOAD " or " FLASH " is still there); run this step again\n");
    else put("DONE: " PRELOAD " and " FLASH " are gone: the camera starts its programs as the firmware ships it\n");
    out_end();
}
#endif

__attribute__((constructor)) static void fx2boot_ctl(void) { run(); }
