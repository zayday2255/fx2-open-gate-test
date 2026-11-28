/* FX2 1.01 start-up loader: the result file of a kit step (2026-11-28). The same file and the same frame as the kit's other steps
 * (helper/readcheck.c): /tmp_wbshd/readcheck_result.txt, created only if absent, "readcheck 1 level <n>" first, "== done" last, and one
 * outcome line the runner reads: "DONE: ...", "NOTHING TO DO ...", "NOT DONE: ..." or a line with "nothing is written". */
#ifndef FX2BOOT_OUT_H
#define FX2BOOT_OUT_H
#include "fx2boot_sys.h"

#ifndef LEVEL
#error "build with -DLEVEL=<the number in the step's name>"
#endif
#define RESULT_PATH "/tmp_wbshd/readcheck_result.txt"
#define STAGE "/tmp_wbshd/fx2boot"           /* RAM: the files as the kit brings them */
#define FLASH "/etc/fx2boot"                 /* flash (nflasha10): the installed copy */
#define PRELOAD "/etc/ld.so.preload"
#define PRELOAD_TEXT FLASH "/fx2hook.so\n"
#define RUN_LOG "/tmp_wbshd/fx2boot.log"
#define NR_geteuid 175
#define OUT_CAP (1024 * 1024)

static int out_fd = -1;
static u64 out_total;
static void put(const char *s)
{
    u64 n = slen(s);
    if (out_fd < 0 || out_total + n > OUT_CAP) return;
    if (sys_write(out_fd, s, n) != (i64)n) { sys_close(out_fd); out_fd = -1; return; }
    out_total += n;
}
static void putn(i64 v)
{
    char t[24]; u64 k = 0;
    if (v < 0) { t[k++] = '-'; v = -v; }
    utoa((u64)v, t + k);
    put(t);
}
__attribute__((unused)) static void puthex(const u8 *b, u64 n)
{
    static const char d[] = "0123456789abcdef";
    char t[3]; t[2] = 0;
    for (u64 i = 0; i < n; i++) { t[0] = d[b[i] >> 4]; t[1] = d[b[i] & 15]; put(t); }
}
/* `n` bytes as they are, in one write. */
__attribute__((unused)) static void putblock(const u8 *b, u64 n)
{
    if (out_fd < 0 || !n || out_total + n > OUT_CAP) return;
    if (sys_write(out_fd, b, n) != (i64)n) { sys_close(out_fd); out_fd = -1; return; }
    out_total += n;
}
/* Text from the camera, made safe to print: printable ASCII and line ends only. */
__attribute__((unused)) static void puttext(const u8 *b, u64 n)
{
    char t[2]; t[1] = 0;
    for (u64 i = 0; i < n; i++) { t[0] = (b[i] == '\n' || (b[i] >= 32 && b[i] < 127)) ? (char)b[i] : '.'; put(t); }
}

/* 1 when this run owns the result file. A result already there (an earlier step's, not fetched yet) means: do nothing at all. */
static int out_begin(const char *title)
{
    i64 fd = sys_open(RESULT_PATH, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) return 0;
    out_fd = (int)fd;
#define OUT_STR2(x) #x
#define OUT_STR(x) OUT_STR2(x)
    put("readcheck 1 level " OUT_STR(LEVEL) "\neuid "); putn(sc(NR_geteuid, 0, 0, 0, 0, 0, 0)); put("\n== level " OUT_STR(LEVEL) ": "); put(title); put("\n");
    return 1;
}
static void out_end(void)
{
    put("== done, bytes written before this line: "); putn((i64)out_total); put("\n");
    if (out_fd >= 0) sys_close(out_fd);
    out_fd = -1;
}

/* Whole file into buf (at most cap bytes). Returns the size, -1 when it cannot be opened, -2 when it is longer than cap. */
__attribute__((unused)) static i64 slurp(const char *path, u8 *buf, u64 cap)
{
    i64 fd = sys_open(path, O_RDONLY, 0), r;
    u64 n = 0;
    if (fd < 0) return -1;
    while ((r = sys_read(fd, buf + n, cap - n)) > 0) n += (u64)r;
    if (r == 0 && n == cap) { u8 one; if (sys_read(fd, &one, 1) > 0) { sys_close(fd); return -2; } }
    sys_close(fd);
    return r < 0 ? -1 : (i64)n;
}

#endif
