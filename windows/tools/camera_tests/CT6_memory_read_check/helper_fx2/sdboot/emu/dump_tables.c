#include <stdio.h>
#include "fx2_expected.h"
static void hex(const unsigned char *b, unsigned n) { for (unsigned i = 0; i < n; i++) printf("%02x", b[i]); }
int main(void)
{
    printf("id_files\n");
    for (unsigned i = 0; i < sizeof id_files / sizeof id_files[0]; i++) { printf(" %s ", id_files[i].name); hex(id_files[i].sha256, 32); printf("\n"); }
    printf("id_pages\n");
    for (unsigned i = 0; i < sizeof id_pages / sizeof id_pages[0]; i++) { printf(" %#x ", id_pages[i].address); hex(id_pages[i].sha256, 32); printf("\n"); }
    printf("cp_sites\n");
    for (unsigned i = 0; i < sizeof cp_sites / sizeof cp_sites[0]; i++) {
        const struct cp_site *c = &cp_sites[i];
        printf(" %s %#x %u %d ", c->name, c->address, c->length, c->soft);
        hex(c->stock, c->length); printf(" ");
        if (c->target) hex(c->target, c->length); printf("\n");
    }
    printf("lm_sites\n");
    for (unsigned i = 0; i < sizeof lm_sites / sizeof lm_sites[0]; i++) {
        const struct mp_site *e = &lm_sites[i];
        printf(" %#lx %u ", e->offset, e->length); hex(e->stock, e->length); printf(" "); hex(e->target, e->length); printf("\n");
    }
    printf("av_sites\n");
    for (unsigned i = 0; i < sizeof av_sites / sizeof av_sites[0]; i++) {
        const struct mp_site *e = &av_sites[i];
        printf(" %#lx %u ", e->offset, e->length); hex(e->stock, e->length); printf(" "); hex(e->target, e->length); printf("\n");
    }
    printf("av_guards\n");
    for (unsigned i = 0; i < sizeof av_guards / sizeof av_guards[0]; i++) {
        const struct av_guard *g = &av_guards[i];
        printf(" %s %#lx %u ", g->name, g->offset, g->length); hex(g->sha256, 32); printf("\n");
    }
    printf("av_sites_n %zu lm_sites_n %zu\n", sizeof av_sites / sizeof av_sites[0], sizeof lm_sites / sizeof lm_sites[0]);
    return 0;
}
