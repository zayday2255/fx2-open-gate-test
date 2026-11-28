/*
 * fx2cp: coprocessor transfers for a program that is NOT the camera application (FX2 1.01 loader, 2026-11-28).
 *
 * The kit's step libraries (libJit_fx2_L13.so, _H5, _L16, _S16 ...) reach coprocessor memory through three functions of the camera's
 * libsencore.so: dmm_alloc, dmm_free and sen_dma_transfer. Inside the camera application those are already loaded. The loader's helper is a
 * separate process, and loading the real libsencore.so there would also load and start seven more of Sony's libraries (USB, test commands,
 * settings store, OpenSSL). This file gives the same three functions, under the same library name (soname libsencore.so, so the camera's
 * loader takes it where a step library asks for libsencore.so), and nothing else.
 *
 * Each function does what the camera's own does, call for call (libsencore.so 1.01: dmm_alloc 0xeda0, dmm_free 0xefa4,
 * sen_control_cache_cp 0x13b9c, sen_dma_transfer 0x13d90; read from the machine code, modding/FX2_SDBOOT.md):
 *   dmm_alloc(size, &handle)    a reply queue (osal_dynamic_id 0x2a/0x3d), one 0x28-byte message to the memory manager's queue 0x61003c
 *                               {+0 u16 0x20, +4 u32 0x192, +0xc u32 10000, +0x14 u16 size, +0x16 u16 1}, the reply within 10 s
 *                               {+2 s16 error, +0xc u32 handle, +0x18 u64 physical address, +0x20 u32 size}; the reply queue is given back
 *   dmm_free(handle)            the same with {+0 u16 0x23, +8 u32 handle, +0x16 u16 2}
 *   sen_dma_transfer(dir, src, dst, size)
 *                               first the coprocessor's cache for the range: one 0x150-byte message to queue 0x928a0770, sent and answered
 *                               in one call {+0x18 u64 coprocessor address, +0x20 u32 size, +0x26 u16 1 when writing}, answer byte +1 = 1;
 *                               then /dev/pcidma, ioctl 0x40185001 with {u8 0, u8 5, u8 dir, u8 0, u32 size, u64 src, u64 dst}
 * The message calls are those of the camera's libosal_uipc.so, the library Sony's own stand-alone tools use for the same queues
 * (/usr/bin/app_monio.elf: the memory manager's queue, from a process of its own).
 *
 * Left out on purpose: coprocessor addresses from 0xf0000000 up (the camera's function translates those through a second call; no step of
 * this kit uses one). Such a transfer is refused here.
 *
 * Every failure returns what the camera's function would (0 / nonzero) and adds one line to /tmp_wbshd/fx2boot.log.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long u64;

/* libosal_uipc.so (argument registers as the camera's own callers load them) */
extern int osal_dynamic_id(int op, int kind, unsigned long id_or_pointer);
extern int osal_valloc_msg_wait(u32 queue, void **msg, u32 size, int wait);
extern void osal_set_msg_src(void *msg, u32 source);
extern int osal_snd_msg(u32 queue, void *msg);
extern int osal_snd_sync_msg(u32 queue, void *msg);
extern int osal_rcv_msg_tmo(u32 queue, void **msg, u32 ms);
extern int osal_free_msg(u32 queue, void *msg);
/* libc */
extern int open(const char *path, int flags, ...);
extern int close(int fd);
extern long write(int fd, const void *buf, unsigned long n);
extern int ioctl(int fd, unsigned long request, ...);

#define Q_DMM 0x0061003cU
#define Q_CACHE 0x928a0770U
#define PCIDMA_TRANSFER 0x40185001UL
#define LOG "/tmp_wbshd/fx2boot.log"

static void say(const char *what, long v)
{
    char line[96]; unsigned n = 0;
    static const char head[] = "fx2cp: ";
    for (unsigned i = 0; head[i]; i++) line[n++] = head[i];
    for (unsigned i = 0; what[i] && n < 70; i++) line[n++] = what[i];
    line[n++] = ' ';
    unsigned long u = v < 0 ? (unsigned long)-v : (unsigned long)v;
    char t[20]; unsigned k = 0;
    do { t[k++] = (char)('0' + u % 10); u /= 10; } while (u);
    if (v < 0) line[n++] = '-';
    while (k) line[n++] = t[--k];
    line[n++] = '\n';
    int fd = open(LOG, 02101, 0600);                 /* O_WRONLY | O_CREAT | O_APPEND */
    if (fd >= 0) { write(fd, line, n); close(fd); }
}

/* u64 dmm_alloc(u32 size, u32 *handle): the physical address of a buffer in main memory, 0 on failure. */
u64 fx2cp_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
u64 fx2cp_dmm_alloc(u32 size, u32 *handle)
{
    u32 reply_q = 0;
    void *msg = 0, *rep = 0;
    u64 phys = 0;
    int r = osal_dynamic_id(0x2a, 0x3d, (unsigned long)&reply_q);
    if (r) { say("dmm_alloc: no reply queue", r); return 0; }
    r = osal_valloc_msg_wait(Q_DMM, &msg, 0x28, 1);
    if (r) say("dmm_alloc: no message", r);
    else {
        u8 *m = msg;
        osal_set_msg_src(msg, reply_q);
        *(u16 *)(m + 0) = 0x20;
        *(u16 *)(m + 0x16) = 1;
        *(u32 *)(m + 4) = 0x192;
        *(u16 *)(m + 0x14) = (u16)size;
        *(u32 *)(m + 0xc) = 10000;
        r = osal_snd_msg(Q_DMM, msg);
        if (r) { say("dmm_alloc: send failed", r); osal_free_msg(Q_DMM, msg); }
        else if ((r = osal_rcv_msg_tmo(reply_q, &rep, 10000)) != 0) say("dmm_alloc: no reply", r);
        else {
            const u8 *p = rep;
            short err = *(const short *)(p + 2);
            if (err) say("dmm_alloc: the memory manager answered", err);
            else if (*(const u32 *)(p + 0x20) < size) say("dmm_alloc: buffer smaller than asked", (long)*(const u32 *)(p + 0x20));
            else { *handle = *(const u32 *)(p + 0xc); phys = *(const u64 *)(p + 0x18); }
            osal_free_msg(reply_q, rep);
        }
    }
    osal_dynamic_id(0x4a, 0, reply_q);
    return phys;
}

void fx2cp_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
void fx2cp_dmm_free(u32 handle)
{
    u32 reply_q = 0;
    void *msg = 0, *rep = 0;
    int r = osal_dynamic_id(0x2a, 0x3d, (unsigned long)&reply_q);
    if (r) { say("dmm_free: no reply queue", r); return; }
    r = osal_valloc_msg_wait(Q_DMM, &msg, 0x28, 1);
    if (r) say("dmm_free: no message", r);
    else {
        u8 *m = msg;
        osal_set_msg_src(msg, reply_q);
        *(u16 *)(m + 0) = 0x23;
        *(u32 *)(m + 8) = handle;
        *(u16 *)(m + 0x16) = 2;
        r = osal_snd_msg(Q_DMM, msg);
        if (r) { say("dmm_free: send failed", r); osal_free_msg(Q_DMM, msg); }
        else if ((r = osal_rcv_msg_tmo(reply_q, &rep, 10000)) != 0) say("dmm_free: no reply", r);
        else {
            short err = *(const short *)((const u8 *)rep + 2);
            if (err) say("dmm_free: the memory manager answered", err);
            osal_free_msg(reply_q, rep);
        }
    }
    osal_dynamic_id(0x4a, 0, reply_q);
}

/* The coprocessor's own cache for [addr, addr + size): before a read it writes out what it holds, after a write it drops it. */
static int cache_cp(u32 dir, u64 addr, u32 size)
{
    void *msg = 0;
    int r = osal_valloc_msg_wait(Q_CACHE, &msg, 0x150, 1);
    if (r) { say("cache: no message", r); return -1; }
    u8 *m = msg;
    *(u16 *)(m + 0x26) = (u16)(dir != 0);
    *(u64 *)(m + 0x18) = addr;
    *(u32 *)(m + 0x20) = size;
    r = osal_snd_sync_msg(Q_CACHE, msg);
    if (r) say("cache: send failed", r);
    else if (m[1] != 1) { say("cache: the coprocessor answered", m[1]); r = -1; }
    osal_free_msg(Q_CACHE, msg);
    return r ? -1 : 0;
}

/* u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size): dir 0 = coprocessor (src) to main memory (dst), 1 = the other way; 0 on success. */
u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size)
{
    struct { u8 zero, five, dir, pad; u32 size; u64 src, dst; } req;
    u64 cp = dir ? dst : src;
    if (cp >= 0xf0000000UL) { say("transfer: an address from 0xf0000000 up is not handled here", 0); return (u32)-1; }
    if (cache_cp(dir, cp, size)) return (u32)-1;
    int fd = open("/dev/pcidma", 2);
    if (fd < 0) { say("transfer: /dev/pcidma could not be opened", fd); return (u32)fd; }
    req.zero = 0; req.five = 5; req.dir = (u8)dir; req.pad = 0;
    req.size = size; req.src = src; req.dst = dst;
    int r = ioctl(fd, PCIDMA_TRANSFER, &req);
    close(fd);
    if (r) say("transfer: the ioctl answered", r);
    return (u32)r;
}
