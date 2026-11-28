/*
 * fx2hook: the start-up hook of the FX2 1.01 loader (2026-11-28). The camera's dynamic loader (glibc 2.25) reads /etc/ld.so.preload for every
 * program it starts and loads the libraries named there; this is the one named there. Its constructor runs in each such program, before the
 * program's own code.
 *
 * What the camera does at power-on decides what this can do (modding/FX2_SDBOOT.md):
 *   - The camera application (im.elf) is NOT started at power-on. It is part of the memory image the firmware ships (nflasha5) and is put back
 *     as it was; after a switch-off with the battery in it is kept in memory. So this library is never loaded into it, and nothing here tries.
 *   - Small helper programs ARE started after every power-on (the Bluetooth start script and its tools, among others). This library is loaded
 *     into each of them. The first one after a power-on starts the loader's helper once, as a process of its own; all others return at once.
 *
 * In every program, the constructor does this and nothing else:
 *   1. reads the kernel's count of completed suspends (the first line of /sys/kernel/debug/suspend_stats). It is 0 only on a cold boot (no
 *      memory image was resumed) or when it cannot be read: then nothing more is done. It is 1 after a battery change and one more after
 *      each switch-off with the battery in: it names the power-on.
 *   2. tries to create the file /tmp_wbshd/fx2boot.g<count> (a RAM disk). Only one program per power-on can: every other gets "exists" and
 *      returns. Cost for those: four system calls, no file on flash touched.
 *   3. the one that made the file starts a child and waits the instant it takes that child to start a second one and end; the program then
 *      goes on as if nothing had happened, with no child of ours and no file descriptor of ours.
 * The second child belongs to nobody. It closes every descriptor it inherited, makes its own session, checks that the installed files are
 * exactly this build's (size and SHA-256 of each, from the list compiled in) and that /etc/fx2boot/off is absent, and only then runs the
 * helper script with the camera's own shell. Anything not as expected: one line in /tmp_wbshd/fx2boot.log and it ends. It writes no flash.
 *
 * No library is used and nothing is imported (build_fx2boot.sh checks). The camera's loader ignores a preload it cannot load ("cannot be
 * preloaded: ignored"), so a missing or damaged copy of this file leaves every program as it was.
 */
#include "fx2boot_sys.h"
#include "fx2boot_manifest.h"            /* FX2BOOT_BUILD, struct fx2boot_file, fx2boot_files[] (gen_fx2boot.py) */

#ifndef HOOK_DIR
#define HOOK_DIR "/etc/fx2boot"
#endif
#ifndef RUN_DIR
#define RUN_DIR "/tmp_wbshd"
#endif
#define STATS "/sys/kernel/debug/suspend_stats"
#define LOG RUN_DIR "/fx2boot.log"
#define SHELL "/bin/busybox"
#define MAX_FILE (256 * 1024)

static void say(const char *a, const char *b)
{
    i64 fd = sys_open(LOG, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0) return;
    sys_write(fd, "hook: ", 6);
    sys_write(fd, a, slen(a));
    sys_write(fd, b, slen(b));
    sys_write(fd, "\n", 1);
    sys_close(fd);
}

/* The number after "success: " at the start of the file; 0 when the file is not there or does not begin so. Kept for the status
 * report and for anyone reading this build: it is NOT what decides whether the helper runs (see claim_boot), because it reads 0 after
 * a battery pull and is absent in the camera application's namespace. */
__attribute__((unused)) static u64 power_on_number(void)
{
    static const char want[] = "success: ";
    char b[32];
    u64 v = 0, k = sizeof want - 1;
    i64 fd = sys_open(STATS, O_RDONLY, 0);
    if (fd < 0) return 0;
    i64 n = sys_read(fd, b, sizeof b);
    sys_close(fd);
    if (n < (i64)k + 1) return 0;
    for (u64 i = 0; i < k; i++) if (b[i] != want[i]) return 0;
    if (b[k] < '0' || b[k] > '9') return 0;
    for (; k < (u64)n && b[k] >= '0' && b[k] <= '9'; k++) {
        if (v > 100000000UL) return 0;
        v = v * 10 + (u64)(b[k] - '0');
    }
    return v;
}

/* The seconds since this power-on, from /proc/uptime ("40.93 120.05") in MILLISECONDS, or 0 when it cannot be read.
 *
 * Milliseconds, not seconds: the hook runs in the very first program of a boot, when /proc/uptime still reads "0.87" - truncating
 * that to whole seconds gives 0, and a 0 was treated as "cannot read", so the helper never ran after a battery pull. That was the
 * second half of the cold-boot fault (2026-11-28). The fraction is what makes an early boot distinguishable from a failure. */
static u64 uptime_ms(void)
{
    char b[48];
    u64 whole = 0, frac = 0;
    int digits = 0, fd = -1;
    fd = (int)sys_open("/proc/uptime", O_RDONLY, 0);
    if (fd < 0) return 0;
    i64 n = sys_read(fd, b, sizeof b);
    sys_close(fd);
    if (n < 1) return 0;
    i64 i = 0;
    for (; i < n && b[i] >= '0' && b[i] <= '9'; i++) {
        if (whole > 100000000UL) return 0;
        whole = whole * 10 + (u64)(b[i] - '0');
        digits++;
    }
    if (digits && i < n && b[i] == '.') {                 /* up to three fraction digits, as milliseconds */
        u64 mul = 100;
        for (i++; i < n && b[i] >= '0' && b[i] <= '9' && mul; i++) {
            frac += (u64)(b[i] - '0') * mul;
            mul /= 10;
        }
    }
    if (!digits) return 0;
    return whole * 1000UL + frac;
}

/* The boot's mark value: /proc/uptime in milliseconds, or 0 when it cannot be read.
 *
 * Two earlier attempts were wrong and are recorded here so they are not repeated:
 *   - CLOCK_MONOTONIC minus the uptime UNDERFLOWED to a huge u64 when the monotonic clock was smaller than the uptime, so every
 *     program claimed a fresh boot and the camera started dozens of helpers a boot. That put it into a restart loop.
 *   - Uptime alone cannot tell "later in this boot" from "a later boot", because both are larger numbers. Any time window either
 *     started a second helper in a long boot or skipped a short one.
 *
 * So the boot is identified by WHEN THE HELPER WAS CLAIMED, and the helper is claimed only inside an early window of the boot: the
 * loader must apply shortly after power-on, before the camera application has set up its movie pipeline, so claiming at 20 s is the
 * whole job. Once a boot is past that window the loader does nothing at all - which is the fail-closed behaviour this needs, because
 * applying late is what crashed the camera (2026-11-28). Inside the window the mark's value is compared exactly, so exactly one
 * program claims it. */
static u64 boot_mark(void)
{
    return uptime_ms();                                   /* 0 when unreadable */
}

/* The start time written in the mark, 0 when there is none. */
static u64 mark_value(void)
{
    u8 b[24];
    u64 v = 0;
    int digits = 0;
    i64 fd = sys_open(RUN_DIR "/fx2boot.mark", O_RDONLY, 0);
    if (fd < 0) return 0;
    i64 n = sys_read(fd, b, sizeof b);
    sys_close(fd);
    for (i64 i = 0; i < n && b[i] >= '0' && b[i] <= '9'; i++) { v = v * 10 + (u64)(b[i] - '0'); digits++; }
    return digits ? v : 0;
}

/* 1 when this program should start the helper. *mark_out receives the boot's uptime, computed ONCE.
 *
 * The rule is a claim token, not a comparison of times. Every program of a boot runs at a different uptime, so no comparison of
 * uptime values can tell "same boot" from "next boot" - two earlier attempts here got that wrong (one started a helper per program
 * and put a camera into a restart loop). Instead:
 *
 *   - the hook creates /tmp_wbshd/fx2boot.run with O_EXCL, and only the program that creates it starts the helper;
 *   - the HELPER deletes that file as its very first action, so it exists for a few milliseconds only;
 *   - every later program of this boot also fails to create it, because the helper is long gone... no: the file is deleted, so a
 *     later program WOULD create it. So the helper instead writes /tmp_wbshd/fx2boot.done and never removes it, and the hook
 *     refuses while that file exists;
 *   - the RAM disk is wiped by a battery pull, and /tmp_wbshd survives a power switch, so /tmp_wbshd/fx2boot.done is cleared
 *     exactly when a boot should get a fresh claim. A warm boot (no RAM reset) keeps it, which is correct: the patch is already in
 *     the image processor, and the helper must not run twice.
 *
 * This is the rule the original build used with one mark per power-on number; the fault was only ever the source of the number. */
#define DONE RUN_DIR "/fx2boot.done"
static int claim_boot(u64 *mark_out)
{
    u64 now = boot_mark();
    *mark_out = now;
    if (!now) { say("no uptime (/proc/uptime unreadable): nothing started", ""); return 0; }
    if (sys_exists(DONE)) return 0;                      /* this boot already had its helper */
    i64 fd = sys_open(DONE, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) return 0;                                /* another program of this boot won the race */
    char num[24];
    utoa(now, num);
    sys_write(fd, num, slen(num));
    sys_close(fd);
    return 1;
}

static int installed_as_built(void)
{
    char path[160];
    u8 got[32];
    for (u64 i = 0; i < sizeof fx2boot_files / sizeof fx2boot_files[0]; i++) {
        const struct fx2boot_file *f = &fx2boot_files[i];
        if (!join(path, sizeof path, HOOK_DIR "/", f->name)) return 0;
        if (sha_file(path, MAX_FILE, got) != (i64)f->size || !same(got, f->sha256, 32)) { say("not this build's file, nothing started: ", f->name); return 0; }
    }
    return 1;
}

static void helper(const char *number) __attribute__((noreturn));
static void helper(const char *number)
{
    for (int fd = 0; fd < 1024; fd++) sys_close(fd);                 /* nothing of the program that started us stays open (its pipes above all) */
    if (sys_open("/dev/null", O_RDWR, 0) == 0) { sc(NR_dup3, 0, 1, 0, 0, 0, 0); sc(NR_dup3, 0, 2, 0, 0, 0, 0); }
    sc(NR_setsid, 0, 0, 0, 0, 0, 0);
    if (sys_exists(HOOK_DIR "/off")) say("switched off by " HOOK_DIR "/off; nothing started, power-on ", number);
    else if (installed_as_built()) {
        const char *argv[] = { "busybox", "sh", HOOK_DIR "/fx2boot.sh", HOOK_DIR, number, FX2BOOT_BUILD, 0 };    /* the applet is named, not implied by argv[0] */
        const char *envp[] = { "PATH=/sbin:/bin:/usr/sbin:/usr/bin", "HOME=/", 0 };
        sc(NR_execve, (i64)SHELL, (i64)argv, (i64)envp, 0, 0, 0);
        say("the shell could not be started; power-on ", number);
    }
    sc(NR_exit_group, 0, 0, 0, 0, 0, 0);
    for (;;) { }
}

__attribute__((constructor)) static void fx2hook(void)
{
    char boot[24];
    u64 mark = 0;
    /* One helper per power-on, decided by /proc/uptime alone (see boot_mark and is_new_boot). Not by the suspend count: that reads
     * 0 after a battery pull and is absent in the camera application's namespace. Never by subtracting CLOCK_MONOTONIC from the
     * uptime: that underflowed and started a helper in every program of a boot, which put a camera into a restart loop. */
    if (!claim_boot(&mark)) return;
    utoa(mark, boot);
    i64 pid = sc(NR_clone, SIGCHLD, 0, 0, 0, 0, 0);
    if (pid == 0) {
        if (sc(NR_clone, SIGCHLD, 0, 0, 0, 0, 0) == 0) helper(boot);
        sc(NR_exit_group, 0, 0, 0, 0, 0, 0);
    }
    if (pid > 0) sc(NR_wait4, pid, 0, 0, 0, 0, 0);
}
