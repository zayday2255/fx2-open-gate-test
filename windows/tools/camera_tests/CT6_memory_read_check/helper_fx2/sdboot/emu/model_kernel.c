/* EMULATION ONLY: stands in for the camera kernel's /dev/pcidma driver in the test sandbox (emu_fx2boot.py). Never sent to a camera.
 *
 * On the camera the transfer between coprocessor memory and main memory is one ioctl (0x40185001) on /dev/pcidma, done by the kernel. In the
 * sandbox /dev/pcidma is an empty file, and this library, preloaded there, answers that one ioctl; every other ioctl goes to the C library.
 *   request: {u8 0, u8 5, u8 dir, u8 0, u32 size, u64 src, u64 dst}; dir 0 = coprocessor (src) to main memory (dst), 1 = the other way
 *   coprocessor memory = the file /emu/cpram.bin (offset = coprocessor address); main memory = /dev/mem (a file there; offset = physical address)
 * Rules checked, as helper_fx2/emu_fx2_write.py checks them for the same libraries: whole 64-byte lines, at most one page, to or from the
 * one buffer the memory manager's stand-in hands out (model_osal.c), coprocessor address inside 0x108000..0x10000000. A request that breaks
 * one is refused and logged as BAD. Every transfer is written to /emu/pcidma.log; for a write, also every byte it changes.
 * Test switch: /emu/fail_ioctl makes the ioctl fail.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define PCIDMA_TRANSFER 0x40185001UL
#define BUF_PHYS 0x47f000000UL
#define BUF_SIZE 0x2000UL
#define CP_LO 0x108000UL
#define CP_HI 0x10000000UL

struct req { unsigned char zero, five, dir, pad; unsigned size; unsigned long src, dst; };

static void logline(const char *fmt, unsigned long a, unsigned long b, unsigned long c)
{
    FILE *f = fopen("/emu/pcidma.log", "a");
    if (!f) return;
    fprintf(f, "%d ", (int)getpid());
    fprintf(f, fmt, a, b, c);
    fputc('\n', f);
    fclose(f);
}

static int transfer(const struct req *q)
{
    static unsigned char now[4096], data[4096];
    unsigned long cp = q->dir ? q->dst : q->src, buf = q->dir ? q->src : q->dst;
    if (q->zero != 0 || q->five != 5 || q->dir > 1 || q->pad != 0 || q->size == 0 || q->size > 4096 || (q->size & 63) || (cp & 63)
        || cp < CP_LO || cp + q->size > CP_HI || buf < BUF_PHYS || buf + q->size > BUF_PHYS + BUF_SIZE) {
        logline("BAD transfer dir %lu coprocessor 0x%lx buffer 0x%lx", q->dir, cp, buf);
        logline("BAD   size 0x%lx head %lu %lu", q->size, q->zero, q->five);
        return -1;
    }
    if (access("/emu/fail_ioctl", F_OK) == 0) { logline("transfer refused by the test switch", 0, 0, 0); return -1; }
    int cpf = open("/emu/cpram.bin", O_RDWR), mem = open("/dev/mem", O_RDWR);
    int r = -1;
    if (cpf >= 0 && mem >= 0) {
        if (q->dir == 0) {
            if (pread(cpf, data, q->size, (off_t)cp) == (ssize_t)q->size && pwrite(mem, data, q->size, (off_t)buf) == (ssize_t)q->size) r = 0;
            logline("read  coprocessor 0x%lx size 0x%lx -> %ld", cp, q->size, (unsigned long)r);
        } else {
            if (pread(mem, data, q->size, (off_t)buf) == (ssize_t)q->size && pread(cpf, now, q->size, (off_t)cp) == (ssize_t)q->size
                && pwrite(cpf, data, q->size, (off_t)cp) == (ssize_t)q->size) r = 0;
            logline("WRITE coprocessor 0x%lx size 0x%lx -> %ld", cp, q->size, (unsigned long)r);
            for (unsigned k = 0; r == 0 && k < q->size; k++)
                if (now[k] != data[k]) logline("  byte 0x%lx: 0x%02lx -> 0x%02lx", cp + k, now[k], data[k]);
        }
    }
    if (cpf >= 0) close(cpf);
    if (mem >= 0) close(mem);
    return r;
}

int ioctl(int fd, unsigned long request, ...)
{
    static int (*next)(int, unsigned long, ...);
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if ((request & 0xffffffffUL) == PCIDMA_TRANSFER) {
        char path[64], link[64];
        snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
        ssize_t n = readlink(link, path, sizeof path - 1);
        if (n > 0) path[n] = 0;
        if (n <= 0 || strcmp(path, "/dev/pcidma") != 0) { logline("BAD: the transfer ioctl on a descriptor that is not /dev/pcidma", 0, 0, 0); return -1; }
        return transfer(arg);
    }
    if (!next) next = dlsym(RTLD_NEXT, "ioctl");
    return next ? next(fd, request, arg) : -1;
}
