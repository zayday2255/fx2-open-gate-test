/* LOCAL (2026-11-28, not from the kit author): a 3:2 picture in the FX2's viewfinder, on top of S16 (lcd32dsq_fx2_v1). */
/* With the open gate the camera holds the 3:2 frame squeezed into a 16:9 display picture. S16 fills the 3:2 rear panel with it */
/* (fit word 0x1f9eec), but the 4:3 viewfinder letterboxes it as 16:9, so it looks squeezed. The viewfinder follows De-Squeeze */
/* Display (measured on an FX2 1.01 with og2560: Off 1.78:1, 1.3x 1.93:1, 2.0x 2.97:1). This step makes the 1.3x entry */
/* height = width x 2/3 = 1.5:1, so with De-Squeeze Display 1.3x the viewfinder shows the whole frame at its true 3:2 shape, and */
/* the rear screen stays 3:2 (as with Off). Code (decoded): 0x1fa162 mov.w sb, #d ; 0x1fa166 mov.w sl, #n ; S16's d 39 / n 20 -> */
/* d 3 / n 2. The same two words as A16 (dsq15_fx2_v1): use one or the other. Its stock bytes are S16's applied bytes, so it refuses */
/* unless S16 is in place. E17 puts back S16's 1.95:1; a cold boot puts back everything. Guards as in dsq15_fx2_v1. Display only. */
#define WORDS_DESIGN "dsq32_fx2_v1"
struct ram_word { u32 address; u8 stock[4]; u8 changed[4]; };
static const struct ram_word ram_words[] = {
    { 0x1fa164, { 0x27, 0x09, 0x4f, 0xf0 }, { 0x03, 0x09, 0x4f, 0xf0 } },
    { 0x1fa168, { 0x14, 0x0a, 0x03, 0xe0 }, { 0x02, 0x0a, 0x03, 0xe0 } },
};
struct ram_guard { u32 address; u32 len; u8 bytes[16]; };
static const struct ram_guard ram_guards[] = {
    { 0x1fa158, 12, { 0x4f, 0xf0, 0x1a, 0x09, 0x4f, 0xf0, 0x0f, 0x0a, 0x08, 0xe0, 0x4f, 0xf0, 0,0,0,0 } },
    { 0x1fa16c, 8, { 0x4f, 0xf0, 0x02, 0x09, 0x4f, 0xf0, 0x01, 0x0a, 0,0,0,0,0,0,0,0 } },
};
