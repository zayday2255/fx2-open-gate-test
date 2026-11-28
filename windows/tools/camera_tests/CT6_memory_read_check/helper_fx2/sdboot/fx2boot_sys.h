/* FX2 1.01 start-up loader ("sdboot"), shared by its freestanding parts (2026-11-28). No library is used: every call into the kernel is one
 * of the numbered system calls below (AArch64 Linux). Nothing here allocates memory. */
#ifndef FX2BOOT_SYS_H
#define FX2BOOT_SYS_H

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;
typedef long i64;

#define NR_dup3 24
#define NR_unlinkat 35
#define NR_renameat 38
#define NR_mkdirat 34
#define NR_faccessat 48
#define NR_openat 56
#define NR_close 57
#define NR_getdents64 61
#define NR_read 63
#define NR_write 64
#define NR_fsync 82
#define NR_exit_group 94
#define NR_clock_gettime 113
#define NR_setsid 157
#define NR_clone 220
#define NR_execve 221
#define NR_wait4 260
#define AT_FDCWD (-100)
#define AT_REMOVEDIR 0x200
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 0100
#define O_EXCL 0200
#define O_TRUNC 01000
#define O_APPEND 02000
#define O_DIRECTORY 040000          /* AArch64 */
#define SIGCHLD 17
#define EEXIST 17

__attribute__((unused)) static i64 sc(i64 n, i64 a, i64 b, i64 c, i64 d, i64 e, i64 f)
{
    register i64 x8 __asm__("x8") = n;
    register i64 x0 __asm__("x0") = a;
    register i64 x1 __asm__("x1") = b;
    register i64 x2 __asm__("x2") = c;
    register i64 x3 __asm__("x3") = d;
    register i64 x4 __asm__("x4") = e;
    register i64 x5 __asm__("x5") = f;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return x0;
}

#define sys_open(p, fl, mode) sc(NR_openat, AT_FDCWD, (i64)(p), (fl), (mode), 0, 0)
#define sys_close(fd) sc(NR_close, (fd), 0, 0, 0, 0, 0)
#define sys_read(fd, b, n) sc(NR_read, (fd), (i64)(b), (i64)(n), 0, 0, 0)
#define sys_write(fd, b, n) sc(NR_write, (fd), (i64)(b), (i64)(n), 0, 0, 0)
#define sys_unlink(p) sc(NR_unlinkat, AT_FDCWD, (i64)(p), 0, 0, 0, 0)
#define sys_rmdir(p) sc(NR_unlinkat, AT_FDCWD, (i64)(p), AT_REMOVEDIR, 0, 0, 0)
#define sys_mkdir(p, mode) sc(NR_mkdirat, AT_FDCWD, (i64)(p), (mode), 0, 0, 0)
#define sys_exists(p) (sc(NR_faccessat, AT_FDCWD, (i64)(p), 0, 0, 0, 0) == 0)

__attribute__((unused)) static u64 slen(const char *s) { u64 n = 0; while (s[n]) n++; return n; }
__attribute__((unused)) static int same(const u8 *a, const u8 *b, u64 n) { for (u64 i = 0; i < n; i++) if (a[i] != b[i]) return 0; return 1; }
__attribute__((unused)) static int streq(const char *a, const char *b) { u64 i = 0; for (; a[i] && b[i]; i++) if (a[i] != b[i]) return 0; return a[i] == b[i]; }

/* dst := a followed by b; returns 0 when it does not fit (dst then holds an empty string). */
__attribute__((unused)) static int join(char *dst, u64 cap, const char *a, const char *b)
{
    u64 n = slen(a), m = slen(b);
    if (n + m + 1 > cap) { dst[0] = 0; return 0; }
    for (u64 i = 0; i < n; i++) dst[i] = a[i];
    for (u64 i = 0; i <= m; i++) dst[n + i] = b[i];
    return 1;
}

/* Decimal text of v into buf (at least 21 bytes); returns its length. */
__attribute__((unused)) static u64 utoa(u64 v, char *buf)
{
    char t[20]; u64 n = 0, k = 0;
    do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) buf[k++] = t[--n];
    buf[k] = 0;
    return k;
}

/* SHA-256 (FIPS 180-4), as in fx2read.c. */
struct sha { u32 h[8]; u8 buf[64]; u64 n, total; };
static const u32 sha_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2 };
static u32 sha_ror(u32 x, int n) { return (x >> n) | (x << (32 - n)); }
static void sha_block(struct sha *s, const u8 *p)
{
    u32 w[64], a[8];
    for (int i = 0; i < 16; i++) w[i] = (u32)p[4 * i] << 24 | (u32)p[4 * i + 1] << 16 | (u32)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        u32 s0 = sha_ror(w[i - 15], 7) ^ sha_ror(w[i - 15], 18) ^ (w[i - 15] >> 3), s1 = sha_ror(w[i - 2], 17) ^ sha_ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    for (int i = 0; i < 8; i++) a[i] = s->h[i];
    for (int i = 0; i < 64; i++) {
        u32 t1 = a[7] + (sha_ror(a[4], 6) ^ sha_ror(a[4], 11) ^ sha_ror(a[4], 25)) + ((a[4] & a[5]) ^ (~a[4] & a[6])) + sha_k[i] + w[i];
        u32 t2 = (sha_ror(a[0], 2) ^ sha_ror(a[0], 13) ^ sha_ror(a[0], 22)) + ((a[0] & a[1]) ^ (a[0] & a[2]) ^ (a[1] & a[2]));
        a[7] = a[6]; a[6] = a[5]; a[5] = a[4]; a[4] = a[3] + t1; a[3] = a[2]; a[2] = a[1]; a[1] = a[0]; a[0] = t1 + t2;
    }
    for (int i = 0; i < 8; i++) s->h[i] += a[i];
}
__attribute__((unused)) static void sha_init(struct sha *s)
{
    static const u32 h0[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
    for (int i = 0; i < 8; i++) s->h[i] = h0[i];
    s->n = 0; s->total = 0;
}
__attribute__((unused)) static void sha_add(struct sha *s, const u8 *p, u64 n)
{
    s->total += n;
    for (u64 i = 0; i < n; i++) {
        s->buf[s->n++] = p[i];
        if (s->n == 64) { sha_block(s, s->buf); s->n = 0; }
    }
}
__attribute__((unused)) static void sha_end(struct sha *s, u8 out[32])
{
    u64 bits = s->total * 8;
    u8 pad = 0x80;
    sha_add(s, &pad, 1);
    pad = 0;
    while (s->n != 56) sha_add(s, &pad, 1);
    for (int i = 7; i >= 0; i--) { u8 b = (u8)(bits >> (8 * i)); sha_add(s, &b, 1); }
    for (int i = 0; i < 8; i++) { out[4 * i] = (u8)(s->h[i] >> 24); out[4 * i + 1] = (u8)(s->h[i] >> 16); out[4 * i + 2] = (u8)(s->h[i] >> 8); out[4 * i + 3] = (u8)s->h[i]; }
}

/* SHA-256 of a whole file, at most `cap` bytes. Returns the size, or -1 (cannot be read, or longer than cap). */
__attribute__((unused)) static i64 sha_file(const char *path, u64 cap, u8 out[32])
{
    static u8 blk[4096];
    struct sha s;
    i64 fd = sys_open(path, O_RDONLY, 0), r;
    if (fd < 0) return -1;
    sha_init(&s);
    while ((r = sys_read(fd, blk, sizeof blk)) > 0) {
        if (s.total + (u64)r > cap) { sys_close(fd); return -1; }
        sha_add(&s, blk, (u64)r);
    }
    sys_close(fd);
    if (r < 0) return -1;
    i64 size = (i64)s.total;
    sha_end(&s, out);
    return size;
}

#endif
