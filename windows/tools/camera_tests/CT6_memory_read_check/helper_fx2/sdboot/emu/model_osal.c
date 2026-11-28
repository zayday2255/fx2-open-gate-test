/* EMULATION ONLY: stands in for the camera's /usr/lib/libosal_uipc.so in the test sandbox (emu_fx2boot.py). Never sent to a camera.
 *
 * It serves the two queues fx2cp.so talks to, as the decompiled libsencore.so 1.01 shows the camera's side of them:
 *   0x0061003c  the memory manager: request {+0 u16 0x20 alloc | 0x23 free, +4 u32 0x192 (alloc), +8 u32 handle (free), +0xc u32 timeout (alloc),
 *               +0x14 u16 size (alloc), +0x16 u16 1 alloc | 2 free}; reply on the sender's queue {+2 s16 error, +0xc u32 handle, +0x18 u64 physical
 *               address, +0x20 u32 size}
 *   0x928a0770  the coprocessor's cache: {+0x18 u64 address, +0x20 u32 size, +0x26 u16 1 = after a write}; answer byte +1 = 1
 * A message is handed out filled with 0xA5, so a field the caller forgets to set is seen. Every call is written to /emu/osal.log, and a
 * request that is not exactly as the camera's own library sends it is logged as BAD and refused.
 * Test switches (files): /emu/fail_dmm (the memory manager answers an error), /emu/fail_cache (the cache answer is 0), /emu/no_reply.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define Q_DMM 0x0061003cU
#define Q_CACHE 0x928a0770U
#define BUF_PHYS 0x47f000000UL
#define BUF_HANDLE 0x00001234U
#define BUF_SIZE 0x2000U

struct hdr { unsigned magic, queue, size, src; };
static void *pending;                 /* the one reply waiting on the dynamic queue */
static unsigned dyn_id, dyn_live;

static void logf_(const char *fmt, unsigned long a, unsigned long b, unsigned long c)
{
    FILE *f = fopen("/emu/osal.log", "a");
    if (!f) return;
    fprintf(f, "%d ", (int)getpid());
    fprintf(f, fmt, a, b, c);
    fputc('\n', f);
    fclose(f);
}

static void *new_msg(unsigned queue, unsigned size)
{
    struct hdr *h = malloc(sizeof *h + size);
    if (!h) return 0;
    h->magic = 0x4d534721; h->queue = queue; h->size = size; h->src = 0;
    memset(h + 1, 0xA5, size);
    return h + 1;
}
static struct hdr *hdr_of(void *msg) { struct hdr *h = (struct hdr *)msg - 1; return h->magic == 0x4d534721 ? h : 0; }

int osal_dynamic_id(int op, int kind, unsigned long arg)
{
    if (op == 0x2a && kind == 0x3d) {
        if (dyn_live) { logf_("BAD dynamic_id: a second reply queue while one is live", 0, 0, 0); return -1; }
        dyn_id = 0x7f3d0001; dyn_live = 1;
        *(unsigned *)arg = dyn_id;
        logf_("dynamic_id alloc -> 0x%lx", dyn_id, 0, 0);
        return 0;
    }
    if (op == 0x4a && kind == 0) {
        if (!dyn_live || (unsigned)arg != dyn_id) { logf_("BAD dynamic_id free of 0x%lx", arg, 0, 0); return -1; }
        dyn_live = 0;
        logf_("dynamic_id free 0x%lx", arg, 0, 0);
        return 0;
    }
    logf_("BAD dynamic_id op 0x%lx kind 0x%lx", (unsigned long)op, (unsigned long)kind, 0);
    return -1;
}

int osal_valloc_msg_wait(unsigned queue, void **msg, unsigned size, int wait)
{
    int ok = (queue == Q_DMM && size == 0x28 && wait == 1) || (queue == Q_CACHE && size == 0x150 && wait == 1);
    if (!ok) { logf_("BAD valloc queue 0x%lx size 0x%lx wait %lu", queue, size, (unsigned long)wait); return -1; }
    *msg = new_msg(queue, size);
    return *msg ? 0 : -1;
}

void osal_set_msg_src(void *msg, unsigned src)
{
    struct hdr *h = hdr_of(msg);
    if (h) h->src = src;
}

int osal_snd_msg(unsigned queue, void *msg)
{
    struct hdr *h = hdr_of(msg);
    unsigned char *m = msg;
    if (!h || queue != Q_DMM || h->queue != Q_DMM || !dyn_live || h->src != dyn_id) { logf_("BAD snd_msg queue 0x%lx", queue, 0, 0); return -1; }
    unsigned short op = *(unsigned short *)(m + 0), kind = *(unsigned short *)(m + 0x16);
    unsigned char *r = 0;
    if (op == 0x20 && kind == 1 && *(unsigned *)(m + 4) == 0x192 && *(unsigned *)(m + 0xc) == 10000) {
        unsigned size = *(unsigned short *)(m + 0x14);
        r = new_msg(dyn_id, 0x28);
        memset(r, 0, 0x28);
        if (access("/emu/fail_dmm", F_OK) == 0 || size > BUF_SIZE) *(short *)(r + 2) = -5;
        else { *(unsigned *)(r + 0xc) = BUF_HANDLE; *(unsigned long *)(r + 0x18) = BUF_PHYS; *(unsigned *)(r + 0x20) = BUF_SIZE; }
        logf_("dmm alloc size 0x%lx -> error %ld", size, (long)*(short *)(r + 2), 0);
    } else if (op == 0x23 && kind == 2) {
        unsigned handle = *(unsigned *)(m + 8);
        r = new_msg(dyn_id, 0x28);
        memset(r, 0, 0x28);
        if (handle != BUF_HANDLE) *(short *)(r + 2) = -6;
        logf_("dmm free handle 0x%lx -> error %ld", handle, (long)*(short *)(r + 2), 0);
    } else {
        logf_("BAD dmm request op 0x%lx kind 0x%lx word4 0x%lx", op, kind, *(unsigned *)(m + 4));
        return -1;
    }
    free(h);                                           /* the receiver owns a sent message */
    if (access("/emu/no_reply", F_OK) == 0) { free(hdr_of(r)); r = 0; }
    pending = r;
    return 0;
}

int osal_rcv_msg_tmo(unsigned queue, void **msg, unsigned ms)
{
    if (!dyn_live || queue != dyn_id || ms != 10000) { logf_("BAD rcv_msg_tmo queue 0x%lx ms %lu", queue, ms, 0); return -1; }
    if (!pending) { logf_("rcv_msg_tmo: nothing came (time-out)", 0, 0, 0); return -0x3fe; }
    *msg = pending;
    pending = 0;
    return 0;
}

int osal_free_msg(unsigned queue, void *msg)
{
    struct hdr *h = hdr_of(msg);
    if (!h || h->queue != queue) { logf_("BAD free_msg queue 0x%lx", queue, 0, 0); return -1; }
    h->magic = 0;
    free(h);
    return 0;
}

int osal_snd_sync_msg(unsigned queue, void *msg)
{
    struct hdr *h = hdr_of(msg);
    unsigned char *m = msg;
    if (!h || queue != Q_CACHE || h->queue != Q_CACHE) { logf_("BAD snd_sync_msg queue 0x%lx", queue, 0, 0); return -1; }
    unsigned short after_write = *(unsigned short *)(m + 0x26);
    if (after_write > 1) { logf_("BAD cache request: direction word 0x%lx", after_write, 0, 0); return -1; }
    logf_("cache dir %lu addr 0x%lx size 0x%lx", after_write, *(unsigned long *)(m + 0x18), *(unsigned *)(m + 0x20));
    m[1] = access("/emu/fail_cache", F_OK) == 0 ? 0 : 1;
    return 0;
}
