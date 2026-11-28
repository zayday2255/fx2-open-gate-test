/*
 * fx2boot_put: one kit step that brings one piece of one loader file to the camera's RAM disk (FX2 1.01 loader, 2026-11-28).
 *
 * The kit sends a library, the camera application loads it once (the service file-write command), and this constructor runs. It writes the
 * bytes it carries to /tmp_wbshd/fx2boot/<name>.part (first piece: a new file; a later piece: appended, and only if the file holds exactly
 * the pieces before it), reads the file back and compares, and renames it to <name> when the last piece is in. /tmp_wbshd is a RAM disk the
 * camera's own start-up script makes: NOTHING HERE WRITES FLASH, and a battery change removes it all.
 *
 * The file is not used by anything until the "run now" or the "install" step has checked the whole set against the build's list of sizes and
 * SHA-256 values. No library is used and nothing is imported.
 */
#include "fx2boot_out.h"
#include PUT_H            /* PUT_NAME, PUT_TOTAL, PUT_OFFSET, put_bytes[] (build_fx2boot.py) */

#define CHUNK (sizeof put_bytes)
static u8 back[PUT_TOTAL > 0 ? PUT_TOTAL : 1];

__attribute__((constructor)) static void fx2boot_put(void)
{
    if (!out_begin("bring " PUT_NAME " to the RAM disk (" STAGE "), a piece of the start-up loader; no flash is written")) return;
    const char *part = STAGE "/" PUT_NAME ".part", *final = STAGE "/" PUT_NAME;
    i64 r = sys_mkdir(STAGE, 0700);
    if (r < 0 && r != -EEXIST) { put("!! the folder " STAGE " could not be made ("); putn(r); put("); nothing is written\n"); out_end(); return; }
    if (PUT_OFFSET) {                                               /* a later piece: the pieces before it must be there, and nothing more */
        i64 have = slurp(part, back, sizeof back);
        if (have != (i64)PUT_OFFSET) {
            put("!! this is the piece from byte "); putn((i64)PUT_OFFSET); put(", and the file on the RAM disk holds "); putn(have);
            put(" bytes (-1: none): send the pieces in order; nothing is written\n");
            out_end(); return;
        }
    }
    i64 fd = sys_open(part, PUT_OFFSET ? (O_WRONLY | O_APPEND) : (O_WRONLY | O_CREAT | O_TRUNC), 0700);
    if (fd < 0) { put("!! the file could not be opened for writing ("); putn(fd); put("); nothing is written\n"); out_end(); return; }
    i64 w = sys_write(fd, put_bytes, CHUNK);
    sys_close(fd);
    i64 have = slurp(part, back, sizeof back);
    if (w != (i64)CHUNK || have != (i64)(PUT_OFFSET + CHUNK) || !same(back + PUT_OFFSET, put_bytes, CHUNK)) {
        sys_unlink(part);
        put("NOT DONE: the piece did not read back as sent (written "); putn(w); put(", file "); putn(have); put(" bytes); the unfinished file was removed\n");
        out_end(); return;
    }
    if (PUT_OFFSET + CHUNK < PUT_TOTAL) {
        put("DONE: " PUT_NAME ": bytes "); putn((i64)PUT_OFFSET); put(" to "); putn((i64)(PUT_OFFSET + CHUNK)); put(" of "); putn((i64)PUT_TOTAL);
        put(" are on the RAM disk; the next piece is still to come\n");
    } else {
        r = sc(NR_renameat, AT_FDCWD, (i64)part, AT_FDCWD, (i64)final, 0, 0);
        if (r < 0) { put("NOT DONE: the finished file could not be given its name ("); putn(r); put(")\n"); out_end(); return; }
        put("DONE: " PUT_NAME " is on the RAM disk, whole ("); putn((i64)PUT_TOTAL); put(" bytes, read back and compared)\n");
    }
    out_end();
}
