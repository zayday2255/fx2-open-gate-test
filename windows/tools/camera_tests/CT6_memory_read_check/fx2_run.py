"""FX2 (ILME-FX2) firmware 1.01: run one of the two READ-ONLY helper libraries, or one write step, and save what it reports.
(Second kit, 2026-11-26: read helper fx2read_v2, the diagnostic ladder's step pair B5/B6, the dump decodes the memory manager's
workspace and the first pages of the crash snapshot image.)
(Fourth kit, 2026-11-26, after L13 + L5 + L16 crashed on MOVIE: read helper fx2read_v4, step pairs H5/H6 (ogh2560_fx2_v1: records whose
first scaler gives 4336x2560) and F16/F17 (fehold_fx2_v1, the fallback's code word); the dump decodes the saved resize view and the
output records at their real address 0x15cdef8.)
(Fifth kit, 2026-11-27, PAL and GitHub issue 5: read helper fx2read_v5 (the check also reports mode 0x880's cells and stored record,
pal_*), step pairs Q5/Q6 (ogsq880_fx2_v1: the squeeze for mode 0x880, the 25p mode of a PAL-set FX2) and P5/P6 (ogh2560880_fx2_v1: the
real rows for mode 0x880); the report says which sensor-side design is in place, whether the camera is set to NTSC or PAL, and warns of
the state the power switch leaves (coprocessor stock, main processor still holding L19).)

  python fx2_run.py check --dry-run | --selftest
  python fx2_run.py dump  --dry-run | --selftest
  python fx2_run.py check --go --firmware-shown 1.01
  python fx2_run.py dump  --go --firmware-shown 1.01 [--clear-result SHA256]
  (write steps: through fx2_apply.py only)

  check   identity of the camera's software and what every site of the open-gate designs holds now: READY / NOT READY
          (the screen step's words are reported as well, not counted: it is optional)
  dump    the same, plus kernel and memory facts, the coprocessor's logs and some of its tables (sensor registers, stored
          records, the scaler's state, the memory manager's records, the display: panel type, fit word, frame tables, de-squeeze words)

Both read-only libraries only read. Each creates one file, its result, on the camera's RAM disk; this script fetches it. The
library is written to the camera's service partition, loaded once, and deleted again in the same session.

The FX2 counterpart of fx3_run.py (the FX3 kit, whose libraries ran on two FX3s), made from it on 2026-11-25 with this camera's
libraries, pins and result reader. The FX2 is the A7 IV's sensor on the A7C II's platform: its write steps are the A7 IV kit's
designs (which work on an A7 IV), ported. Nothing here can send a memory write unless a write step is named with --writes-memory.
"""
import argparse
import collections
import json
import platform
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "helper"))
sys.path.insert(0, str(HERE / "helper_fx2"))
import ct1_common as c  # noqa: E402
import ct6_level1_run as R  # noqa: E402

FIRMWARE, MODEL, BUILD = "1.01", "ILME-FX2", "fx2_101"
S3 = HERE / "helper_fx2"                       # this kit's folder (the name S3 is kept from s3_run.py)
PINS = {"check": ("libJit_fx2_check.so", "a5bfb54714b684ada9e24076be1a007f77c2caa1b058c89c34d07984760c87cb"),      # fx2read_v5 (2026-11-27, fifth kit: PAL sites)
        "dump": ("libJit_fx2_dump.so", "8ad8e1ff4a341ab2b8ce2118d0ad6a17076d72b3aaa8be33e025cf6159f48345")}
# fx2read_v4 (fourth kit, ran on two FX2s 2026-11-26): check 97516ead..., dump f4cb345a...
# fx2read_v3 (third kit, ran on the tester's FX2 2026-11-26): check 696c9be6..., dump 6a234dde...
# fx2read_v2 (second kit, ran on the tester's FX2 2026-11-26): check 9dd469a2..., dump 1f51dc2a...
# the first kit's read helper (fx2read_v1, 2026-11-25; ran on the first tester's FX2): check e3838945..., dump 5008ec3a...
LEVELS = {"check": 101, "dump": 102}              # numbers outside the A7 IV runner's own levels: none of its level-specific code runs
# THE WRITE STEPS. Each is one library built from the A7 IV helper's write code with this camera's tables (helper_fx2/build_fx2_write.sh).
# They change the running camera's memory until a cold boot. They are run through fx2_apply.py, never by a launcher of the read-only kit,
# and the libraries are not in the published kit unless it was published with --include-write.
WRITE_STEPS = {
    # The A7 IV kit's raw write buffer step (its level 13/14, dmmwb4688_v1): on the FX2, as on the A7 IV, the movie raw write buffer holds the
    # stock 3,958-row stage only (27,864,320 bytes); the full-height stage needs 4,688 rows. Must run first, from a cold boot with the camera on STILL.
    "L13": ("libJit_fx2_L13.so", "c99682a38445ad82974b94527da56f8ac8caec860a7c5b64ae3e6ba2992f1d4f", "apply the raw write buffer dmmwb4688_fx2_v1 (four memory-manager words: the movie raw write buffer holds 4,688 rows)"),
    "L14": ("libJit_fx2_L14.so", "15ec15af57c1590e0b832783c1939c9af41645cf0519a69f72282ad3cd99f991", "put back the raw write buffer dmmwb4688_fx2_v1"),
    "L5": ("libJit_fx2_L5.so", "724174438d0aaeae8c4ba1f611371cade6f7224c11c8b1441bd84e11107cafa9", "apply the sensor-side design ogsq_fx2_v1 (sensor cells, two records, the stored record; the A7 IV's working ogsq_v3)"),
    "L6": ("libJit_fx2_L6.so", "ae85bce19d3d0d73253c03a2fedbdc9e16f2097d5acf751430cf754049a78d5b", "put back the sensor-side design ogsq_fx2_v1"),
    # Second kit (2026-11-26), the diagnostic ladder's test 1: the same levels 5/6 with fhband_fx2_v1 = the A7 IV's fhband_v1 (F658, worked on the
    # A7 IV): the sensor in the same full-height mode as L5 (the 11 cells are L5's), but the picture records keep the stock 16:9 band, so the stage
    # has its stock height. Tells whether the FX2 runs the full-height read-out at all.
    "B5": ("libJit_fx2_B5.so", "23e19cbeac5e4378783abe75a9dde5547ac246912c90b6ec8ea77489a0defefc", "apply the test design fhband_fx2_v1 (full-height read-out with the stock 16:9 band: the A7 IV's fhband_v1)"),
    "B6": ("libJit_fx2_B6.so", "ea9c86281af81203176c9fd2b7d7511a7f85b2c5e6c71df2df0f2434a2eb1377", "put back the test design fhband_fx2_v1"),
    # Fourth kit (2026-11-26), after test 3 (L13 + L5 + L16) crashed on MOVIE entry. The FX2's resize set-up (0x51fbc0) raises the first-scaler
    # size it hands the second scaler to at least the output size (0xbd3a32; only the FX2 and the A1 II have it), so with the 3840x2560 output
    # size it says 4336x2560 while L5's records make the first scaler give 4336x2438 (build/emu_rcinput_fx2.py). H5 = the same levels 5/6 with
    # ogh2560_fx2_v1 = the A7 IV's ogh2560_v1 (F712, F713: works on the A7 IV): L5's sensor cells and stored record, records whose first
    # scaler gives 4336x2560. It takes L5's place.
    "H5": ("libJit_fx2_H5.so", "47be321cecb37fcba26c0e2b7e8017c931ad339d37bf4e131d3d46f3ed6f7bf5", "apply the sensor-side design ogh2560_fx2_v1 (L5's sensor cells and stored record, with records whose first scaler gives 4336x2560: the A7 IV's ogh2560_v1)"),
    "H6": ("libJit_fx2_H6.so", "e459d65ca595895933165fa2b3a78de136789d69e0c825a749f32c4e09a74528", "put back the sensor-side design ogh2560_fx2_v1"),
    # Q5/Q6, P5/P6 (fifth kit, 2026-11-27): PAL. On a PAL-set FX2 4K 25p runs drive mode 0x880 and its stored record comes from the 50 Hz
    # input table, so the 0x8c0 steps (L5, H5) refuse there and these refuse on NTSC. Q = L5 moved to mode 0x880 (the A7 IV's ogsq880_v1, which
    # works on a PAL A7 IV), P = H5 moved to mode 0x880 (the record pair is shared by 0x880 and 0x8c0)
    "Q5": ("libJit_fx2_Q5.so", "04c9fd0fbec1206cb14f11828cffd82e791aa21713b52c4fc332d021cce8f783", "apply the sensor-side design ogsq880_fx2_v1 for PAL (mode 0x880, 25p: sensor cells, two records, the stored record; L5 moved to 0x880)"),
    "Q6": ("libJit_fx2_Q6.so", "7a8ae5846d90d92599df0fcd32ce1cac9bbb2c8cbf6ea9ef79916560600e13e0", "put back the sensor-side design ogsq880_fx2_v1 (PAL)"),
    "P5": ("libJit_fx2_P5.so", "b3b6094d843d59c514e67915019025dba7f23830051648334ee2a81e5f4653d9", "apply the sensor-side design ogh2560880_fx2_v1 for PAL (mode 0x880, 25p: H5 moved to 0x880, records whose first scaler gives 4336x2560)"),
    # K5/K6, J5/J6, K16/K17 (2026-11-27, GitHub issue 7: 5.7K, the A7 IV's real 5760x3840 state F906): the sensor side with records whose
    # first scaler gives 5760x3840 (K = mode 0x8c0, NTSC; J = mode 0x880, PAL), and the output side (four scaler units, the 0x43f buffer, 5760x3840)
    "K5": ("libJit_fx2_K5.so", "fb776e4a4550def3066cd1680ecc981524ffcf8a656a60dd81d100a83393883d", "apply the sensor-side design og57n_fx2_v1 for 5.7K (mode 0x8c0, NTSC: L5's sensor cells and stored record, records whose first scaler gives 5760x3840: the A7 IV's og57n_v1)"),
    "K6": ("libJit_fx2_K6.so", "2acafe84e8a094451e800887d2e07894014cee1f98e01ee39774f86982d1fe8f", "put back the sensor-side design og57n_fx2_v1"),
    "J5": ("libJit_fx2_J5.so", "189f919aabbda9ebfa0fab2c659d9f43f080ec91851f9c3662722cfdef28c805", "apply the sensor-side design og57n880_fx2_v1 for 5.7K on PAL (mode 0x880, 25p: Q5's cells and stored record, the 5760x3840 records)"),
    "J6": ("libJit_fx2_J6.so", "61f5e86de8ae2ec08390dd7a005ae3cd7e0fc791e472a2fb2a5f89cd3449a23f", "put back the sensor-side design og57n880_fx2_v1 (PAL)"),
    "K16": ("libJit_fx2_K16.so", "a175e9a5cf8cc3aff600051316f67146ee1eb829898d94cebef390bfbbaf4252", "apply the output side og57cp_fx2_v3 for 5.7K (four scaler units, a 30.8 MB output buffer as id 0x43f, the output size 5760x3840: five words)"),
    "K17": ("libJit_fx2_K17.so", "a50174f7d2ee8535e4d7a1ee08106055a46d0d54c7f8ce2b6630f8d6ac8659b3", "put back the output side og57cp_fx2_v3"),
    "P6": ("libJit_fx2_P6.so", "5b892e4c904507cf3e610852b06239d77c077164ae4386ffae480cd6b806271f", "put back the sensor-side design ogh2560880_fx2_v1 (PAL)"),
    "L16": ("libJit_fx2_L16.so", "744dd7eb1b8f0cd79fde6f508b39988e9c92bc37ef1f10f30783ce2ae2ee441a", "apply the output size outsz2560_fx2_v1 (one word)"),
    "L17": ("libJit_fx2_L17.so", "d2d62a12fc2f99f69423fa42d96e9650be6c8aba30982b11d281a5925d2e5098", "put back the output size outsz2560_fx2_v1"),
    # Fourth kit, the FALLBACK (with L5, not with H5): the same level 16/17 code with one CODE word of the resize set-up, 0x51fefa
    # `cbz r0, 0x51ff22` -> `b 0x51ff22`, so the override is skipped and the second scaler enlarges 2,438 rows to 2,560 as on the A7 IV.
    "F16": ("libJit_fx2_F16.so", "73a87e6d00be9c5e3b1ba57e15b147f11edba09306254ed2c49e8ae4c9afcad2", "apply the code word fehold_fx2_v1 (the resize set-up keeps the first-scaler size the records give: one word)"),
    "F17": ("libJit_fx2_F17.so", "6cc77afdb1308029b0924af8d03bb3bae562d76a17a54bf4465a5613c42c5d2a", "put back the code word fehold_fx2_v1"),
    # L19/L20: ogfile2560_hs_s_fx2_v2 = the A7 IV's encoder side (101 + 4 sites) + the two MP4 header heights, so tkhd, stsd and Sony's PROF say
    # 3840x2560 (the A7 IV's working ogfile2560_hs_s_v2). L20 puts back either version. N19 = the same without the heights (apply --no-meta).
    "L19": ("libJit_fx2_L19.so", "e2a695989c05bdb4261892f46414d5b9d9bf42e87f30c6103035834beefb3525", "apply the encoder-side design ogfile2560_hs_s_fx2_v2 (101 + 4 sites, and the MP4 headers say 3840x2560: 2 more)"),
    "L20": ("libJit_fx2_L20.so", "decff5bf679512a5004c133d37b6131c93424e4a52c29e570baf884c119eb4eb", "put back the encoder-side design ogfile2560_hs_s_fx2_v2 (or v1)"),
    # 2026-11-27 (GitHub issue 7): the 5.7K encoder side and XAVC S-I 4K
    "K19": ("libJit_fx2_K19.so", "27278ae59a0264df5d410eb2b6b25efffdc984251b042efc366787b01adbac40", "apply the encoder-side design ogfile57r300m1_fx2_v4 for 5.7K (296 + 14 sites: two encoder cores, 300 Mbps on the 100M+ settings, I and P pictures only, the MP4 headers at 5760x3840: the A7 IV's ogfile57r300m1_v4)"),
    "K20": ("libJit_fx2_K20.so", "24c7b0be46f16e7ad93cefce5bb529ff875ea17bb45de56e697a24f21349ea12", "put back the 5.7K encoder-side design ogfile57r300m1_fx2_v4 (or v3)"),
    "M19": ("libJit_fx2_M19.so", "9d78d348f7046a3dd5c5a79d2fc66b58884e603adf20428694a9702334a105da", "apply the encoder-side design ogfile57r300m1_fx2_v3 for 5.7K (as K19, but the MP4 headers keep 3840x2160: --no-meta)"),
    "I19": ("libJit_fx2_I19.so", "2aa88118db758eebc1fb83ec57c60ffb5bd1eea24cd23ea7412d0b2d3157bc66", "apply the encoder-side design ogfilesi2560_fx2_v1: XAVC S-I 4K at 3840x2560 (16 + 1 sites, on top of L19: the A7 IV's ogfilesi2560_v1)"),
    "I20": ("libJit_fx2_I20.so", "1065aa61ecc6db6bf409f8725a72dfbb0ef7d91430d1ee8eb861d1e230c90f9e", "put back the XAVC S-I 4K step ogfilesi2560_fx2_v1"),
    "G19": ("libJit_fx2_G19.so", "a17334c4c18519846b08f0ed27437eec93d4eb510b205022df052fdb20f487aa", "apply the encoder-side design ogfilesi57_fx2_v1: XAVC S-I 4K at 5760x3840 (24 + 1 sites, on top of K19: the A7 IV's ogfilesi57_v1)"),
    "G20": ("libJit_fx2_G20.so", "37f042b8302703a4d133748b71b0f0224fe9d6df53e02219a9c5045367be6899", "put back the XAVC S-I 4K step ogfilesi57_fx2_v1"),
    "N19": ("libJit_fx2_N19.so", "45a68ca583f6f60f05893f6652a1b7d9556870081c4ec127ed0051527f3e8aec", "apply the encoder-side design ogfile2560_hs_s_fx2_v1 (101 + 4 sites; the MP4 headers keep 3840x2160)"),
    # The rear-screen step (optional, on top of the open-gate state): the same level 16/17 code with the screen words. There is no C step: the
    # FX2's own De-Squeeze Display is kept (its ratios are part of S16).
    "S16": ("libJit_fx2_S16.so", "dd8bb759cef4dc8f9b3c63722d3c51036217bb67bda5967c88ca093d8b8f9df0", "apply the screen words lcd32dsq_fx2_v1 (the 3:2 rear screen filled with the whole picture, the focus-frame rectangles, and De-Squeeze Display ratios for a 3:2 picture: 18 words)"),
    "S17": ("libJit_fx2_S17.so", "34075aa0bf39d67ca5623bc0913599fd3c2ada3916bb2ba99d63bc214339b0d8", "put back the screen words lcd32dsq_fx2_v1"),
    # LOCAL (2026-11-27, not from the kit author): the A7 IV kit's nrsoff_v1 at the FX2's address (helper/expected_words_nrsoff_fx2_v1.h:
    # CamNrOnOff 0x1f43381, guarded by the code that reads it). Same level 16/17 code as S16. Not run on any camera.
    "Z16": ("libJit_fx2_Z16.so", "5500ad1164c29d1c18e04208c328d9941502dd1a773eca8f0b389f0e622193ea", "LOCAL: spatial noise reduction off nrsoff_fx2_v1 (the camera's own switch CamNrOnOff, byte 0x1f43381, 0 to 1)"),
    "Z17": ("libJit_fx2_Z17.so", "baf783cce46f43146fdf756a79f5d398ab7cfd73be1667f8855dc244bd34e57e", "LOCAL: put back spatial noise reduction (nrsoff_fx2_v1)"),
    # LOCAL (2026-11-27): the menu's De-Squeeze Display 1.3x shows 2.25:1 (a 3:2 frame through a 1.5x anamorphic lens) instead of S16's
    # 1.95:1 (helper/expected_words_dsq15_fx2_v1.h). On top of S16 only (its stock bytes are S16's). Display only. Not run on any camera.
    "A16": ("libJit_fx2_A16.so", "cd6f420299a297aab6c2df3665e3b799946615a4220f42d5a4f04e87d1119886", "LOCAL: De-Squeeze Display 1.3x entry shows 2.25:1 for 1.5x anamorphic lenses (dsq15_fx2_v1, on top of S16)"),
    "A17": ("libJit_fx2_A17.so", "f190f3c211b501d1ea8291439d2092b254c5be7a4be8844450eaafe1e0ac4764", "LOCAL: put back S16's 1.3x shape (1.95:1)"),
}
# --- loader steps: begin (helper_fx2/sdboot/update_runner.py writes this block)
# The start-up loader, build fx2boot_v1 ("sdboot": helper_fx2/sdboot/, modding/FX2_SDBOOT.md). W1..W18 bring its files to the camera's RAM disk
# (/tmp_wbshd, nothing on flash), W50..W53 choose what its helper applies (RAM copy), W30 runs the helper once from RAM, W42 reads its status;
# W40 INSTALLS it on flash (/etc/fx2boot and /etc/ld.so.preload) and W41 removes it. A step in LOADER_FLASH can write the camera's flash:
# it needs --writes-flash besides --writes-memory. A battery change does not undo a flash step; W41 does.
LOADER_STEPS = {
    "W1": ("sdboot/libJit_fx2_W1.so", "1791eac2f614139c0a993faf38345003c6b2bed38d93df1b95cdb7694b828e88", "RAM only: bring fx2boot.sh (9306 bytes) of the start-up loader to the camera's RAM disk"),
    "W2": ("sdboot/libJit_fx2_W2.so", "fd2cd066fa8106cf85f2827fd68cc3002e1cf2bb7eaee42dd8b59e8b87d876d7", "RAM only: bring fx2cp.so (6136 bytes) of the start-up loader to the camera's RAM disk"),
    "W3": ("sdboot/libJit_fx2_W3.so", "66c484b9f5736c4aea71fd0e690ebc6f3460a8ba9b9a8469b4ea43cb6e3cf5e2", "RAM only: bring fx2hook.so (7856 bytes) of the start-up loader to the camera's RAM disk"),
    "W4": ("sdboot/libJit_fx2_W4.so", "6465d1e5d4a7c9a9575939aea506410e6e84ad88bec7e25e5ea66382c8d9d64e", "RAM only: bring libJit_fx2_X21.so (65072 bytes, piece 1 of 2) of the start-up loader to the camera's RAM disk"),
    "W5": ("sdboot/libJit_fx2_W5.so", "01fb509ccefd7847f60e2e575d9b18abd1ab7a4935386a77562a7d8a1f9db8d9", "RAM only: bring libJit_fx2_X21.so (65072 bytes, piece 2 of 2) of the start-up loader to the camera's RAM disk"),
    "W6": ("sdboot/libJit_fx2_W6.so", "dc5360657499384a9885faf6678b801f26be9c5af66f940980eb1f58ea7bf963", "RAM only: bring libJit_fx2_X18.so (27280 bytes) of the start-up loader to the camera's RAM disk"),
    "W7": ("sdboot/libJit_fx2_W7.so", "2ae19c6cd31ca61f6fcedf7a9a00f6ab230968be5eff9ca63e1e8c9c5e2e152e", "RAM only: bring libJit_fx2_X19.so (28392 bytes) of the start-up loader to the camera's RAM disk"),
    "W8": ("sdboot/libJit_fx2_W8.so", "34e75c36d596c304b880c52b96c7c447fb1412477fc85965581013cbc8dc0c59", "RAM only: bring libJit_fx2_X20.so (28400 bytes) of the start-up loader to the camera's RAM disk"),
    "W9": ("sdboot/libJit_fx2_W9.so", "caf235f8089590e21dd0a975f5a83737773b2bdae3bb87837254d30abc715131", "RAM only: bring libJit_fx2_X22.so (37632 bytes) of the start-up loader to the camera's RAM disk"),
    "W10": ("sdboot/libJit_fx2_W10.so", "ef2be095aac7652995fb8a27dc16f7920e578c9aba5f91f5facced051d4e1b4a", "RAM only: bring libJit_fx2_L13.so (19832 bytes) of the start-up loader to the camera's RAM disk"),
    "W11": ("sdboot/libJit_fx2_W11.so", "1b67128add8e2794cfa9ba3a762a32ffe73d563bd2d5c6c1cb7eecf12302cb28", "RAM only: bring libJit_fx2_H5.so (31680 bytes) of the start-up loader to the camera's RAM disk"),
    "W12": ("sdboot/libJit_fx2_W12.so", "76260ce812ac04c625a7939bbbf09af1e1096595eb95ea4e549d83d2701803fb", "RAM only: bring libJit_fx2_P5.so (31696 bytes) of the start-up loader to the camera's RAM disk"),
    "W13": ("sdboot/libJit_fx2_W13.so", "87ecd56e2b8fed94187889a8bd0534ea764a278a96f694405e86ab80beb80cb5", "RAM only: bring libJit_fx2_L5.so (31680 bytes) of the start-up loader to the camera's RAM disk"),
    "W14": ("sdboot/libJit_fx2_W14.so", "4473136ca1447937b00e098ca85f1092acb09d6b88b146545b5562703a3107fa", "RAM only: bring libJit_fx2_L16.so (16232 bytes) of the start-up loader to the camera's RAM disk"),
    "W15": ("sdboot/libJit_fx2_W15.so", "4532228cad515c8a6af7f02c26dd2febb0ab7e5a6767e7aea8284626b350f63c", "RAM only: bring libJit_fx2_S16.so (17368 bytes) of the start-up loader to the camera's RAM disk"),
    "W16": ("sdboot/libJit_fx2_W16.so", "a791d854dc558fa4cda2509d7a2890ed1c25373f62f3e4ec7f30479f61c91433", "RAM only: bring libJit_fx2_K5.so (31680 bytes) of the start-up loader to the camera's RAM disk"),
    "W17": ("sdboot/libJit_fx2_W17.so", "c335e1834c83619d4930f5dd772146e782b6dc3c4667ccefe71585aafb11e945", "RAM only: bring libJit_fx2_J5.so (31680 bytes) of the start-up loader to the camera's RAM disk"),
    "W18": ("sdboot/libJit_fx2_W18.so", "5c918c48b513e38885d45a9f5849ef25f6a51f1af3d23b5ba6178ce69a3b9073", "RAM only: bring libJit_fx2_K16.so (16824 bytes) of the start-up loader to the camera's RAM disk"),
    "W30": ("sdboot/libJit_fx2_W30.so", "2890e7f0f36bd191cf10af25b6ef69382e1cc0287175eda7be42ecd6f61a7f9d", "RAM only: start the start-up loader's helper once, now, from the RAM copy (the chosen plan); no flash is written"),
    "W40": ("sdboot/libJit_fx2_W40.so", "b81bb55fdce24db15431c9ca07319783edd6d6c61e58bf02f137f0c452cb023d", "FLASH: install the start-up loader (copies its checked files to /etc/fx2boot and writes /etc/ld.so.preload)"),
    "W41": ("sdboot/libJit_fx2_W41.so", "467c00c9b174c70df6f18e3e5fa601fbfd5e72a624a6574b19a178c85eb234db", "FLASH: uninstall the start-up loader (removes /etc/ld.so.preload first, then /etc/fx2boot and earlier research builds' files)"),
    "W42": ("sdboot/libJit_fx2_W42.so", "b17b15c0a594976be40e02df49651931c31b7f25175c83b31bdc0486a0faccb0", "read-only: status of the start-up loader (what is installed, the plan, the helper's last report)"),
    "W50": ("sdboot/libJit_fx2_W50.so", "7df07b84d27a1316b8511beef2bc845717f0367bf5724fab282457c3d255e052", "RAM only: choose the helper's plan: check (read-only: reads the coprocessor and encoder sites from outside the camera application)"),
    "W51": ("sdboot/libJit_fx2_W51.so", "9535392da6a4a729abe708bfa9845b5aeb681a4c9a6ef71250cda7ff9c98acff", "RAM only: choose the helper's plan: og2560 (the 3840x2560 open gate, 23.98p/24p: L13 H5 L16 X19 S16)"),
    "W52": ("sdboot/libJit_fx2_W52.so", "2a2a107c4754c62e57e54c367ca3291628d88ccc9d2edb005e2222aedcafdca4", "RAM only: choose the helper's plan: og2560pal (the 3840x2560 open gate on a PAL-set camera, 25p: L13 P5 L16 X19 S16)"),
    "W53": ("sdboot/libJit_fx2_W53.so", "59b532cb69262b41ed6cd25c60f0074ec1ac02b2a3295328828087afbc74d678", "RAM only: choose the helper's plan: squeeze (the squeezed open gate: X20 L13 L5 S16)"),
    "W54": ("sdboot/libJit_fx2_W54.so", "2bcd505ecba1148dbca4cfa7922143e15fd45ac42f51e279c9d9cb39498b392e", "RAM only: choose the helper's plan: og57 (5.7K, 5760x3840 at 300 Mbps on the 100M+ settings, 23.98p/24p: L13 K5 K16 X22 S16)"),
    "W55": ("sdboot/libJit_fx2_W55.so", "0b45043b29d485f3accf2ee8b7dcaf4d085f9bbeca109b8272611ba9b0a3110a", "RAM only: choose the helper's plan: og57pal (5.7K on a PAL-set camera, 25p: L13 J5 K16 X22 S16)"),
    "W58": ("sdboot/libJit_fx2_W58.so", "ba809b02d9b60f1f26ead86a216791c6acd140343fe58c2ce3b210538ece59fc", "FLASH (one empty file): switch the start-up hook off (/etc/fx2boot/off)"),
    "W59": ("sdboot/libJit_fx2_W59.so", "513df31447ef35181a467a21a23e499249e7efa3b635aad1635edbb6e02fb7b8", "FLASH: switch the start-up hook on again (removes /etc/fx2boot/off)"),
}
LOADER_STAGE = ("W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10", "W11", "W12", "W13", "W14", "W15", "W16", "W17", "W18")
LOADER_PLANS = {"check": "W50", "og2560": "W51", "og2560pal": "W52", "squeeze": "W53", "og57": "W54", "og57pal": "W55"}                                    # plan name: the step that chooses it
LOADER_FLASH = ("W40", "W41", "W58", "W59")
LOADER_BUILD = "fx2boot_v1"
# --- loader steps: end
WRITE_STEPS.update(LOADER_STEPS)
PINS.update({k: v[:2] for k, v in WRITE_STEPS.items()})
LEVELS.update({k: {"L": 200, "S": 300, "N": 500, "B": 700, "H": 800, "F": 900, "Q": 1000, "P": 1100, "K": 1200, "J": 1300, "I": 1400, "G": 1500, "M": 1600, "Z": 1700, "A": 1800, "W": 3500}[k[0]] + int(k[1:])
               for k in WRITE_STEPS})
WHICH = "check"
FULL_HEIGHT_COLUMN = 5          # the register-matrix column of the full-height read-out (ogsq_fx2_v1's S0: mode 0x8c0 column 6 -> 5, as on the A7 IV)


def write_result(data):
    """The facts of a write step's result (the A7 IV helper's report format)."""
    import hashlib
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    pick = lambda start: next((ln for ln in lines if ln.startswith(start)), None)
    outcome = ("UNDO INCOMPLETE" if pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE") else "DONE" if pick("DONE: ") else "NOTHING TO DO" if pick("NOTHING TO DO") else
               "NOT DONE (everything put back)" if pick("NOT DONE: ") else "NOTHING WRITTEN" if any("nothing is written" in ln for ln in lines) else "UNKNOWN")
    problems = [ln for ln in lines if ln.startswith("!!")]
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": lines[0].startswith("readcheck 1 level %s" % WHICH[1:]),
            "euid": "see the result", "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(problems),
            "complete": any(ln.startswith("== done") for ln in lines[-3:]),
            "s3": {"step": WHICH, "what": WRITE_STEPS[WHICH][2], "outcome": outcome, "ok": outcome in ("DONE", "NOTHING TO DO"),
                   "outcome_line": pick("DONE: ") or pick("NOTHING TO DO") or pick("NOT DONE: ") or pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"), "problem_lines": problems,
                   # a loader step's result is its report (what is installed, the helper's log): it is shown whole, printable characters only
                   "text": [ln for ln in "".join(ch if ch == "\n" or " " <= ch <= "~" else "." for ch in text[:20000]).split("\n")[2:] if ln] if WHICH in LOADER_STEPS else None}}


def reference():
    return json.loads((S3 / "fx2_reference.json").read_text(encoding="utf8"))


def expected():
    return json.loads((S3 / "fx2_expected.json").read_text(encoding="utf8"))


# ------------------------------------------------------------ reading a result

def check_result(data):
    """The facts of a result file. Keys the A7 IV runner prints, plus this helper's own under "s3"."""
    if WHICH in WRITE_STEPS:
        return write_result(data)
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    count = lambda pat: sum(1 for ln in lines if re.search(pat, ln))
    verdict = next((ln for ln in lines if ln.startswith("VERDICT ")), "no verdict line")
    pages = {}
    for ln in lines:
        if ln.startswith("cppage "):
            _, name, addr, hx = ln.split(" ", 3)
            pages[int(addr, 16)] = (name, bytes.fromhex(hx.strip()))
    sites = []
    for ln in lines:
        m = re.match(r"site (\S+) (0x[0-9a-f]+) len (\d+)(?: bytes (?:differing from stock )?(\S+))?  (STOCK|TARGET|TEST2?|OTHER.*|NOT READ)$", ln)
        if m:
            sites.append({"name": m.group(1), "address": m.group(2), "length": int(m.group(3)), "shown": m.group(4), "state": m.group(5)})
    # v5: the bytes the helper prints for a large site that is neither stock nor a design's (line "other <name> <hex>"): the stored records,
    # whose run-time bytes always differ on a camera, are judged by the design's own bytes from these
    other_bytes = {}
    for ln in lines:
        if ln.startswith("other ") and ln.count(" ") == 2:
            _, n_, hx_ = ln.split(" ")
            if re.fullmatch(r"[0-9a-f]+", hx_):
                other_bytes[n_] = hx_
    s3 = {"header": head, "verdict": verdict, "ready": verdict.startswith("VERDICT READY"),
          "identity_same": count(r"SAME as the 1\.01 update$"), "identity_differs": count(r"DIFFERS from the 1\.01 update$"),
          "coprocessor_sites": sites, "libmpr_sites": [ln for ln in lines if ln.startswith("lm ")],
          # 2026-11-27: the bytes of each main-processor site, so that a state other than the 4K design's (5.7K: K19 / M19) can be named
          "avcam_bytes": {m.group(1): m.group(2) for m in (re.match(r"av (0x[0-9a-f]+) bytes ([0-9a-f]+)  ", ln) for ln in lines) if m},
          "libmpr_bytes": {m.group(1): m.group(2) for m in (re.match(r"lm (0x[0-9a-f]+) at 0x[0-9a-f]+ bytes ([0-9a-f]+)  ", ln) for ln in lines) if m},
          "avcam_stock": count(r"^av .*  STOCK$"), "avcam_target": count(r"^av .*  TARGET$"), "avcam_other": count(r"^av .*  OTHER$"),
          "avcam_guards": [ln for ln in lines if ln.startswith("guard ")], "problem_lines": [ln for ln in lines if ln.startswith("!!")],
          "pages": len(pages), "other_bytes": {k: v for k, v in other_bytes.items() if "stored_record" in k or k.startswith("record_")}}
    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)
    s3["kernel_command_line"], s3["kernel_version"] = (cmd.group(1).strip() if cmd else None), (ver.group(1).strip() if ver else None)
    if pages:
        s3["decoded"] = decode_pages(pages)
        # v4: the first-scaler size the saved resize view holds, against the one the picture records in place give
        rv, rd = s3["decoded"].get("resize_view"), reference().get("record_designs", {})
        states = set(record_states(s3).values())
        if rv and len(states) == 1 and next(iter(states)) in rd:
            info = rd[next(iter(states))]
            rv.update(records_in_place=info["design"], first_scaler_by_records=info["first_scaler"], sizes_agree=rv["first_scaler"] == info["first_scaler"])
    import hashlib
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": head.startswith("fx2read ") and "ILME-FX2 1.01" in head, "euid": "not read",
            "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(s3["problem_lines"]), "complete": "== done" in lines[-3:],
            "s3": s3, "_pages": pages}


def decode_pages(pages):
    """What the dump's coprocessor pages say, set against the firmware file's tables."""
    ref, out = reference(), {}

    def mem(addr, n):
        b = bytearray()
        while n:
            page = pages.get(addr & ~0xFFF)
            if page is None:
                return None
            take = min(n, 4096 - (addr & 0xFFF))
            b += page[1][addr & 0xFFF:(addr & 0xFFF) + take]
            addr, n = addr + take, n - take
        return bytes(b)

    # the sensor register shadow against each column of the register matrix (the A7 IV sensor's: 24-byte rows, one byte per column)
    rows = [(a, bytes.fromhex(h)) for a, h in ref["matrix"]]
    ncol = max(ref["column_map"]) + 1
    shadow = [(a, mem(a, 1)) for a, _ in rows]
    if all(v is not None for _, v in shadow):
        score = [sum(1 for (a, cols), (_, v) in zip(rows, shadow) if cols[k] == v[0]) for k in range(ncol)]
        best = max(range(ncol), key=lambda k: score[k])
        users = [ref["mode_ids"][i] for i, col in enumerate(ref["column_map"]) if col == best]
        out["sensor_registers"] = {"rows": len(rows), "rows_equal_per_column": score, "closest_column": best, "modes_using_it": users,
                                   "rows_differing_from_it": [[i, hex(a), cols[best], v[0]] for i, ((a, cols), (_, v)) in enumerate(zip(rows, shadow)) if cols[best] != v[0]][:64],
                                   "register_row0": shadow[0][1][0],
                                   "full_height_column": FULL_HEIGHT_COLUMN}
    # the matrix itself as the camera holds it
    m0 = int(ref["matrix_address"], 16)
    got = mem(m0, 24 * len(rows))
    if got is not None:
        want = b"".join(struct.pack("<I", a) + cols for a, cols in rows)
        out["matrix_equals_file"] = got == want
    # the stored drive-parameter records against the emulated ones
    r0, size = int(ref["records_address"], 16), ref["record_size"]
    recs = {}
    for i, mid in enumerate(ref["mode_ids"]):
        b = mem(r0 + i * size, size)
        if b is None:
            continue
        emu = bytes.fromhex(ref["emulated_stock_records"][mid])
        diff = [o for o in range(size) if b[o] != emu[o]]
        recs[mid] = {"index": i, "all_zero": not any(b), "bytes_differing_from_emulation": len(diff), "offsets": [hex(o) for o in diff[:48]], "record": b.hex()}
    out["stored_records"] = recs
    sd = ref["stored_record_design"]
    v = recs.get(sd["mode"])
    if v:
        b, st, dz = bytes.fromhex(v["record"]), bytes.fromhex(sd["stock"]), bytes.fromhex(sd["design"])
        offs = [k for k in range(size) if st[k] != dz[k]]
        out["stored_record_design_bytes"] = {"stock": sum(b[k] == st[k] for k in offs), "design": sum(b[k] == dz[k] for k in offs), "of": len(offs)}
    # v5 (PAL): mode 0x880's record against the PAL designs' stock (the 50 Hz one) and design bytes
    sp = ref.get("stored_record_design_pal")
    v = recs.get(sp["mode"]) if sp else None
    if v:
        b, st, dz = bytes.fromhex(v["record"]), bytes.fromhex(sp["stock"]), bytes.fromhex(sp["design"])
        offs = [k for k in range(size) if st[k] != dz[k]]
        out["stored_record_design_pal_bytes"] = {"stock": sum(b[k] == st[k] for k in offs), "design": sum(b[k] == dz[k] for k in offs), "of": len(offs)}
    t = mem(int(ref["size_table_address"], 16), 128)
    if t is not None:
        out["size_table"] = [list(struct.unpack_from("<HHI", t, 8 * k)) for k in range(16)]
    # The resize state. The A7 IV's second scaler block (0x145091c: in w, in h, start x, y, w-1, h-1, fractions) moved on the FX2 with a changed
    # layout (build/port_addr.py a7iv_602 fx2_101: its neighbours went to 0x190cf38.. and 0x190d014, not by one shift), so the dump's pages are
    # searched for the sizes that matter instead; the resize working structure is read where the FX2's code builds it (0x15e4298 / 0x15e42d0).
    st_ = {}
    seen = {}
    pairs = {(7008, 4672), (7008, 3942), (7032, 4688), (7032, 3958), (4336, 2438), (4336, 2560), (3840, 2560), (3840, 2160), (1920, 1080),
             (2176, 2438), (2160, 2438), (1928, 2560), (1912, 2560)}
    for addr, (name, blob) in sorted(pages.items()):
        if name not in ("resizestate", "resizework"):
            continue
        for o in range(0, 4096 - 3, 2):
            p = struct.unpack_from("<HH", blob, o)
            if p in pairs:
                seen.setdefault("%dx%d" % p, []).append(hex(addr + o))
    st_["where_sizes_occur"] = {k: v[:40] for k, v in sorted(seen.items())}
    se = mem(0x190EA40, 0x20)
    if se is not None:
        st_["resize_settings_0x190ea40"] = se.hex()
    if any(n in ("resizestate", "resizework") for n, _ in pages.values()):
        out["scaler_state"] = st_
    # the memory manager's RAM copy: the raw write buffer's four words
    rb = ref.get("raw_write_buffer", [])
    if rb and all(mem(int(w["address"], 16), 4) is not None for w in rb):
        got = [mem(int(w["address"], 16), 4).hex() for w in rb]
        out["raw_write_buffer_words"] = {"stock": sum(g == w["stock"] for g, w in zip(got, rb)), "new": sum(g == w["new"] for g, w in zip(got, rb)),
                                         "other": sum(g not in (w["stock"], w["new"]) for g, w in zip(got, rb))}
    # The display (modding/FX2_PORT_SCREEN.md): panel-type bytes 0x19d98cc (rear; 3 = a 3:2 panel, 2 = 4:3, 1 = 16:9; 4 or more counts as 1)
    # and 0x19d99fc (viewfinder). Fit words of a 16:9 picture 0x1f9ee8 (4:3 panel) / 0x1f9eec (3:2 panel): 3 letterbox, 0 fill (screen step).
    disp = {}
    types = mem(0x19D98CC, 1), mem(0x19D99FC, 1)
    if None not in types:
        name = {1: "16:9", 2: "4:3", 3: "3:2"}
        rear, evf = (1 if types[0][0] >= 4 else types[0][0]), (1 if types[1][0] >= 4 else types[1][0])
        disp["panel_types"] = {"rear_0x19d98cc": types[0][0], "rear_aspect": name.get(rear, "none"), "viewfinder_0x19d99fc": types[1][0], "viewfinder_aspect": name.get(evf, "none")}
    fit = mem(0x1F9EE8, 8)
    if fit is not None:
        disp["fit_16x9_picture"] = {"on_4x3_panel": struct.unpack_from("<I", fit, 0)[0], "on_3x2_panel": struct.unpack_from("<I", fit, 4)[0]}
    frames = {}
    for t in (0xF796D4, 0xF7974C, 0xF797C4):
        b = mem(t, 0x78)
        if b is not None:
            frames[hex(t)] = {"row%d" % r: list(struct.unpack_from("<4H", b, 8 * (5 * r + 3))) for r in range(3)}
    if frames:
        disp["frame_rectangles_16x9_picture"] = frames
    sw = ref.get("screen_words", [])
    if sw and all(mem(int(w["address"], 16), 4) is not None for w in sw):
        got = [mem(int(w["address"], 16), 4).hex() for w in sw]
        disp["screen_words"] = {"stock": sum(g == w["stock"] for g, w in zip(got, sw)), "new": sum(g == w["new"] for g, w in zip(got, sw)),
                                "other": sum(g not in (w["stock"], w["new"]) for g, w in zip(got, sw))}
        dsq = [w for w in sw if w["note"].startswith("de-squeeze")]
        if dsq:
            g2 = [mem(int(w["address"], 16), 4).hex() for w in dsq]
            disp["desqueeze_words"] = "stock" if all(g == w["stock"] for g, w in zip(g2, dsq)) else "3:2 picture (screen step applied)" if all(g == w["new"] for g, w in zip(g2, dsq)) else "mixed or unknown"
    if disp:
        out["display"] = disp
    # v2: the memory manager's workspace (build/dmm_dump.py's layout; unit objects of 0x50 bytes at +0x107e0). Live objects are those of the
    # divisions in force; objects of divisions merged back keep their contents for a while: what was opened lately (e.g. the last movie look).
    dm = ref.get("dmm")
    g = mem(int(dm["workspace_pointer"], 16), 4) if dm else None
    if dm and g is not None:
        ws = struct.unpack("<I", g)[0]
        units = ws + dm["units_at"]
        raw = mem(units, dm["objects"] * dm["object_bytes"]) if ws == int(dm["workspace_expected"], 16) else None
        w = {"workspace": hex(ws), "as_expected": raw is not None}
        if raw is not None:
            objs, by_addr = [], {}
            for i in range(dm["objects"]):
                o = raw[i * 0x50:(i + 1) * 0x50]
                flags = struct.unpack_from("<H", o, 2)[0]
                base = struct.unpack_from("<Q", o, 8)[0]
                off, size = struct.unpack_from("<II", o, 0x10)
                parent, key, owner = struct.unpack_from("<III", o, 0x20)
                group = struct.unpack_from("<I", o, 0x30)[0]
                if size == 0 and key == 0:
                    continue
                by_addr[units + i * 0x50] = key
                objs.append({"n": i, "key": key, "address": base + off, "size": size, "owner": owner, "split": bool(flags & 1), "group": group, "parent": parent})
            split = {units + o["n"] * 0x50 for o in objs if o["split"]}
            live = [o for o in objs if not o["parent"] or o["parent"] in split]
            hraw = mem(ws, dm["handles"] * dm["handle_bytes"]) or b""
            hid = {}
            for h in range(len(hraw) // 0x40):
                mem_id = struct.unpack_from("<I", hraw, h * 0x40)[0]
                if mem_id != 0xFFFFFFFF and any(struct.unpack_from("<12I", hraw, h * 0x40 + 0x10)):
                    hid[ws + h * 0x40] = mem_id
            ids = dm["ids_by_key"]
            name = lambda k: "%#x (ids %s)" % (k, ", ".join(ids.get(hex(k), [])) or "-")
            w["live_objects"] = [{"key": name(o["key"]), "size": o["size"], "in_use": o["owner"] != 0,
                                  "opened_as": hex(hid[o["owner"]]) if o["owner"] in hid else None,
                                  "divided_as_group": hex(o["group"]) if o["split"] and o["group"] < 0x400 else None} for o in live]
            left = collections.Counter((o["key"], o["size"]) for o in objs if o not in live)
            w["left_over_objects"] = [{"key": name(k), "size": s, "count": n} for (k, s), n in sorted(left.items())]
            w["left_over_divisions"] = sorted({"%#x as group %#x" % (o["key"], o["group"]) for o in objs if o not in live and 0 < o["group"] < 0x400})
            # the raw write buffer: id 0x43e is key 0x57f (27,864,320 stock, 33,003,520 with L13); id 0x608 is key 0x6a3 (27,864,320, not changed)
            sizes = lambda key: sorted({o["size"] for o in objs if o["key"] == key})
            w["raw_write_buffer_units_seen"] = {"0x57f (id 0x43e)": sizes(0x57F), "0x6a3 (id 0x608)": sizes(0x6A3), "0x704 (id 0x63d)": sizes(0x704)}
        out["memory_manager"] = w
    # v4: the saved resize view (0x15cd520, what 0x51fbc0 filled last): its flag bytes, the first stage, the crop, the first-scaler size it
    # hands the second scaler, the output size and the drive mode; and the margin words 0xbd6f34 can return
    rvf = ref.get("resize_view")
    b = mem(int(rvf["address"], 16), rvf["bytes"]) if rvf else None
    if b is not None:
        pair = lambda o: list(struct.unpack_from("<HH", b, o))
        out["resize_view"] = {"address": rvf["address"], "flags": list(b[:rvf["flags"]]), "follows_output_size": bool(b[5]), "first_stage": pair(rvf["first_stage_at"]),
                              "crop": pair(rvf["crop_at"]), "first_scaler": pair(rvf["first_scaler_at"]), "output": pair(rvf["output_at"]),
                              "mode": hex(struct.unpack_from("<I", b, rvf["mode_at"])[0]), "bytes": b.hex()}
    mw = ref.get("margin_words")
    if mw:
        words, sw_ = mem(int(mw["address"], 16), 2 * mw["count"]), mem(int(mw["switch"], 16), 4)
        if words is not None and sw_ is not None:
            out["margin_words"] = {"address": mw["address"], "words": list(struct.unpack("<%dH" % mw["count"], words)), "switch": struct.unpack("<I", sw_)[0]}
    # v3: the saved output records (the copy the output-buffer chooser 0x51cb38 reads; v4: at 0x15cdef8, where 0xbc75de says they are, not at
    # 0x15cd7e0): size, format code, type, and the picture bytes against the buffer the chooser would take
    orf = ref.get("output_records")
    if orf:
        first = int(orf["first_record"], 16)
        recs_out = []
        for k in range(orf["records"]):
            b = mem(first + orf["stride"] * k, orf["stride"])
            if b is None:
                recs_out = None
                break
            w, h = struct.unpack_from("<HH", b, orf["w_at"])
            code = struct.unpack_from("<I", b, orf["code_at"])[0]
            typ = struct.unpack_from("<I", b, orf["type_at"])[0]
            factor = orf["factor_by_code"].get(str(code))
            recs_out.append({"record": k, "w": w, "h": h, "format_code": code, "type": typ, "picture_bytes": int(w * h * factor) if factor else None,
                             "bytes_at_3840x2560": int(3840 * 2560 * factor) if factor else None})
        if recs_out is not None:
            out["output_records"] = recs_out
    # the coprocessor's kprint log (0xe0000, kept across a restart without power loss): its exception record, if any (GitHub issue 5 part 4:
    # the restart after a frame-rate change left "ip/sp/lr/pc", "Running Task", "cause", "DFAR" lines; pc 0x507dae = the forced exception
    # "FW: S-Ele Refresh ng force exception" at 0x507da0, a pipeline stage still busy after 11 frames)
    kp = b"".join(blob for _, (name, blob) in sorted(pages.items()) if name == "kprint")
    if kp:
        rec = {"pcs": []}
        for s in (x.decode("ascii", "replace") for x in re.findall(rb"[ -~\t]{4,}", kp)):
            m = re.search(r"lr: (0x[0-9a-f]+)\s+pc: (0x[0-9a-f]+)", s)
            if m:
                rec["pcs"].append(m.group(2))
                rec.setdefault("lr", m.group(1))
            for key, pat in (("task", r"Running Task: (\S+)"), ("cause", r"cause: \d+\(([^)]+)\)"), ("dfar", r"DFAR: (0x[0-9a-f]+)"),
                             ("firmware", r"FirmVer: (\S+)")):
                m = re.search(pat, s)
                if m:
                    rec.setdefault(key, m.group(1))
            if "Snapshot Debug Image Saved" in s:
                rec["snapshot_saved"] = True
        rec["exception"] = bool(rec["pcs"])
        rec["forced_refresh_exception"] = any(int(x, 16) in (0x507DAE, 0x507DAC) for x in rec["pcs"])
        out["kprint"] = rec
    # v2: the snapshot debug image's first pages (its format is not known): the tag, whether anything is there, and its printable strings
    sn = ref.get("snapshot")
    if sn:
        a0 = int(sn["address"], 16)
        head = mem(a0, 0x3200)
        if head is not None:
            strings = re.findall(rb"[ -~]{6,}", head)
            out["snapshot_head"] = {"address": sn["address"], "all_zero": not any(head), "first_bytes": head[:64].hex(),
                                    "tag_found": sn["tag"].encode() in head, "nonzero_bytes": sum(1 for x in head if x),
                                    "strings": [s.decode("ascii", "replace") for s in strings[:40]]}
    return out


# ------------------------------------------------------------ the A7 IV runner, pointed at this camera

def known_answer(session, camera):
    want = (S3 / "DeviceInfo.xml").read_bytes()
    there, data = R.read(camera, R.KNOWN_PATH)
    if not there or data != want:
        raise c.StopTest("DeviceInfo.xml is not the file of the 1.01 update (%s); nothing else is sent"
                         % ("the camera returned no file" if not there else "%d bytes, SHA-256 %s" % (len(data), c.sha256(data)[:16])))
    session.say("Known-answer read: DeviceInfo.xml equals the 1.01 file (the A7 IV, A7C II, FX3 and others have the same file: the helper itself checks which camera this is)")


def run_helper(data):
    """What loading the uploaded bytes gives on a model FX2: the real AArch64 code in Unicorn if it is installed, else a canned text."""
    if WHICH in WRITE_STEPS:                        # the write libraries are emulated by helper_fx2/emu_fx2_write.py; here only the session flow is simulated
        text = "readcheck 1 level %s\neuid 0\n== level %s\nDONE: every site holds the target bytes (canned)\n== done, bytes written before this line: 0\n" % (WHICH[1:], WHICH[1:])
        return text.encode(), "canned"
    try:
        import emu_fx2
    except Exception:
        text = "fx2read fx2read_v5 %s for ILME-FX2 1.01; read-only\n== file /proc/version\nLinux (simulated)\n\n== end 18 bytes\n== summary\nVERDICT READY (canned)\n== done\n" % WHICH
        return text.encode(), "canned"
    r, text = emu_fx2.run(bytes(data))
    if r.bad:
        raise AssertionError("the emulated helper stopped: %s" % r.bad)
    return text.encode(), "emulated"


def make_sim(lib, files=None, fault=None):
    sim = _make_sim(lib, files, fault)
    if "/usr/share/pmbp/DeviceInfo.xml" not in (files or {}):
        sim.fs["/usr/share/pmbp/DeviceInfo.xml"] = (S3 / "DeviceInfo.xml").read_bytes()
    return sim


def use(which):
    """Point the runner's module state at one of this camera's libraries."""
    global WHICH
    WHICH = which
    name, sha = PINS[which]
    if not (S3 / name).is_file():
        raise SystemExit("%s is not in this kit%s. Nothing was sent." % (name, " (the write steps are not published yet)" if which in WRITE_STEPS else ""))
    R.LEVEL, R.DESIGN, R.LIB, R.LIB_SHA256 = LEVELS[which], "og4k_data_v1", S3 / name, sha
    R.check_result, R.known_answer, R.run_helper, R.make_sim = check_result, known_answer, run_helper, make_sim
    c.EXPECTED_FIRMWARE = FIRMWARE
    return R.library()


_make_sim = R.make_sim


def selftest(lib):
    done = []

    def check(cond, what):
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    W, D = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = R.simulate(lib, R.body_run)
    r = s.results.get("ct6", {})
    check(not stopped and not sim.unexpected and R.sent(s).count(W) == 1 and R.sent(s).count(D) == 1, "normal run: one write, one delete, nothing off the list")
    check(R.sent(s).index(D) < len(R.sent(s)) - 2 and R.sent(s)[-1] == "GET_FILE2", "normal run: the delete comes before the result is read")
    check(R.LIB_PATH.decode() not in sim.fs and sim.loads == 1, "normal run: the library was loaded once and is gone afterwards")
    f = r.get("result", {}).get("s3", {})
    if WHICH in WRITE_STEPS:
        check(f.get("ok") and r["result"]["header_ok"], "normal run: the step's result is read as DONE")
    else:
        check(f.get("ready") and not f.get("identity_differs"), "normal run: the %s helper reports a stock 1.01 camera as READY" % sim.how)
    if sim.how == "emulated":
        want_sites = [x for x in expected()["cp_sites"] if not (WHICH == "dump" and x.get("check_only"))]     # v5: pal_* in the check only
        check(len(f["coprocessor_sites"]) == len(want_sites) and f["avcam_stock"] == 101 and len(f["libmpr_sites"]) == expected()["lm_sites"] == 6,
              "normal run: every coprocessor site, 6 libmpr (4 rows, 2 MP4 header heights) and 101 av-cam sites are reported")
        check(sum(1 for x in f["coprocessor_sites"] if x["name"].startswith("rawbuf_") and x["state"] == "STOCK") == 4,
              "normal run: the raw write buffer's four memory-manager words are reported STOCK")
        if WHICH == "dump":
            d = f.get("decoded", {})
            check(d.get("matrix_equals_file") and len(d.get("stored_records", {})) == 32 and d.get("size_table"), "dump: the pages decode (matrix, 32 records, size table)")
            check(d.get("raw_write_buffer_words") == {"stock": 4, "new": 0, "other": 0}, "dump: the raw write buffer's words decode as stock")
            mm = d.get("memory_manager", {})
            check(mm.get("as_expected") and mm.get("raw_write_buffer_units_seen", {}).get("0x57f (id 0x43e)") == [33003520]
                  and any(o["opened_as"] == "0x43e" for o in mm.get("live_objects", [])) and mm.get("left_over_objects"),
                  "dump: the memory manager's workspace decodes (model: a 0x43e unit of 33,003,520 bytes open, a left-over 0x6a3 object)")
            check(d.get("snapshot_head", {}).get("all_zero") is True, "dump: the snapshot area's first pages are read (all zero in the model)")
            orr = d.get("output_records") or []
            check([(r["w"], r["h"], r["format_code"]) for r in orr] == [(3840, 2160, 2), (1920, 1080, 2), (1920, 1080, 2), (3840, 2160, 2)],
                  "dump: the saved output records decode (model: 3840x2160 / 1920x1080 x2 / 3840x2160, format code 2)")
            rv = d.get("resize_view", {})
            check(rv.get("flags", [])[4:6] == [1, 1] and rv.get("first_scaler") == [4336, 2438] and rv.get("output") == [3840, 2160] and rv.get("mode") == "0x8c0"
                  and rv.get("records_in_place") == "stock" and rv.get("sizes_agree") is True and d.get("margin_words", {}).get("words") == [0] * 8,
                  "dump: the saved resize view decodes (model: first scaler 4336x2438 as the stock records give, output 3840x2160) and the margin words read")
            dp = d.get("display", {})
            check(dp.get("fit_16x9_picture") == {"on_4x3_panel": 3, "on_3x2_panel": 3}
                  and all(v == {"row0": [0, 60, 640, 360], "row1": [0, 38, 640, 404], "row2": [0, 60, 640, 360]} for v in dp.get("frame_rectangles_16x9_picture", {"x": 0}).values())
                  and len(dp.get("frame_rectangles_16x9_picture", {})) == 3 and dp.get("desqueeze_words") == "stock"
                  and dp.get("screen_words") == {"stock": 18, "new": 0, "other": 0} and "panel_types" in dp,
                  "dump: the display pages decode (fit words, the three tables' rows, de-squeeze words, the 18 screen words, panel types)")
        cs = camera_state(f)
        check(cs["family"].startswith("NTSC") and cs["sensor_side"] == "none (stock)" and cs["encoder_side"] == "stock" and not cs["warning"],
              "normal run: the report reads the model as an NTSC camera with nothing applied, no warning")
        g = dict(f, coprocessor_sites=[dict(x) for x in f["coprocessor_sites"]], avcam_stock=0, avcam_target=101, avcam_other=0)
        check(camera_state(g)["warning"] is not None, "the power-switch state (coprocessor stock, L19 applied): the report warns")
        for x in g["coprocessor_sites"]:
            if re.match(r"(pal_)?S\d+$", x["name"]) or x["name"] in ("record_left", "record_right", "pal_stored_record"):
                x["state"] = "TARGET" if x["name"].startswith("pal_") or x["name"].startswith("record_") else x["state"]
            if x["name"] == "pal_stored_record":
                x["state"] = "TARGET"
        if WHICH == "check":
            check(camera_state(g)["sensor_side"].startswith("Q5") and camera_state(g)["family"].startswith("PAL") and not camera_state(g)["warning"],
                  "a PAL camera with Q5 and L19 (model): read as Q5 on PAL, no warning")
            import emu_fx2
            r_, text_ = emu_fx2.run(bytes(lib), applied=True, enc="ogfile57r300m1_fx2_v4")
            cs_ = camera_state(check_result(text_.encode())["s3"])
            check(not r_.bad and cs_["encoder_side"].startswith("applied (K19"), "the emulated check with the 5.7K encoder step: read as K19 (%s)" % cs_["encoder_side"])
            r_, text_ = emu_fx2.run(bytes(lib), test="og57n_fx2_v1")
            cs_ = camera_state(check_result(text_.encode())["s3"])
            check(not r_.bad and cs_["sensor_side"].startswith("K5 ") and cs_["family"].startswith("NTSC"),
                  "the emulated check with the 5.7K sensor step (og57n_fx2_v1): read as K5 on NTSC (%s)" % cs_["sensor_side"])
            for pal, want in (("stock", "none (stock)"), ("squeeze", "Q5 "), ("real", "P5 ")):
                r_, text_ = emu_fx2.run(bytes(lib), pal=pal)
                cs_ = camera_state(check_result(text_.encode())["s3"])
                check(not r_.bad and cs_["family"].startswith("PAL") and cs_["sensor_side"].startswith(want),
                      "the emulated check on a PAL-set FX2's own records (%s): read as PAL, sensor side %s" % (pal, cs_["sensor_side"]))
    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): b"someone else's"})
    check(stopped and W not in R.sent(s) and D not in R.sent(s), "a foreign libJit.so on the camera: stops, nothing written, nothing deleted")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"old"})
    check(stopped and W not in R.sent(s), "a result already on the RAM disk: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp/jbusy": b""})
    check(stopped and W not in R.sent(s), "/tmp/jbusy present: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/usr/share/pmbp/DeviceInfo.xml": b"<other camera/>"})
    check(stopped and len(R.sent(s)) == 2, "another DeviceInfo.xml: stops after the known-answer read")
    s, sim, stopped = R.simulate(lib, R.body_run, fault="load")
    check(stopped and R.sent(s).count(D) == 1 and R.LIB_PATH.decode() not in sim.fs, "a camera that cannot load the library: it is still deleted")
    check(len(R.refusals(lib)) == 15, "the guard refuses the 15 listed packets (changed library, other paths, backup, flash and debug writes ...)")
    return done


def margin_name(rv):
    """Which SteadyShot margin word a resize view's first-scaler request implies: 0xbd6f34's words are 7208 (SteadyShot Active, 11%) and
    19660 (Dynamic Active, 30%) on every FX2 dump (GitHub issue 5: 4336x2877 with Active, 5486x3658 with Dynamic Active, for 2,560 rows)."""
    rows, out = rv["first_scaler"][1], rv["output"][1]
    if not rows or rows <= out:
        return "none"
    m = round(65536 * (1 - out / rows))
    for word, name in ((7208, "SteadyShot Active, 11%"), (19660, "SteadyShot Dynamic Active, 30%")):
        if abs(m - word) <= 40:
            return name
    return "margin word about %d of 65536" % m


def record_states(f):
    """The two picture records' states: the site's own (STOCK / TARGET / TEST / TEST2), or K57 when the bytes the helper printed for an OTHER
    record are the 5.7K records (og57n_fx2_v1 / og57n880_fx2_v1: no site design of the helper, recognised by SHA-256 on the PC)."""
    import hashlib
    k57 = reference().get("record_designs", {}).get("K57", {}).get("sha256", [])
    out = {}
    for x in f["coprocessor_sites"]:
        if x["name"] in ("record_left", "record_right"):
            s = x["state"]
            hx = f.get("other_bytes", {}).get(x["name"])
            if s.startswith("OTHER") and hx and k57 and hashlib.sha256(bytes.fromhex(hx)).hexdigest() == k57[0 if x["name"] == "record_left" else 1]:
                s = "K57"
            out[x["name"]] = s
    return out


def output_size(f):
    """The movie size table's 4K output word as the check shows it: stock 3840x2160, L16's 3840x2560 or K16's 5760x3840."""
    x = next((x for x in f["coprocessor_sites"] if x["name"] == "outsize"), None)
    if not x:
        return None
    if x["state"] == "STOCK":
        return "3840x2160 (stock)"
    if x["state"] == "TARGET":
        return "3840x2560 (L16)"
    return {"8016000f": "5760x3840 (K16, 5.7K)"}.get(x.get("shown") or "", "other (%s)" % x.get("shown"))


def camera_state(f):
    """v5: which sensor-side design the coprocessor sites show, whether the camera is set to NTSC or PAL, the encoder side's state, and a
    warning for the state the power switch leaves on an FX2 (GitHub issue 5: it restarts the coprocessor, so every coprocessor site is
    stock again, but the main processor keeps L19's sites)."""
    st = {x["name"]: x["state"] for x in f["coprocessor_sites"]}
    cells = {st[k] for k in st if re.match(r"S\d+$", k)}
    pal = {st[k] for k in st if re.match(r"pal_S\d+$", k)}
    recs = set(record_states(f).values()) or {None}
    d = f.get("decoded") or {}
    ref = reference()

    def by_design_bytes(name, key):
        """STOCK / TARGET / OTHER for a stored record from the design's own bytes; the site's state when it is already one of those."""
        s = st.get(name)
        if s in ("STOCK", "TARGET", "TEST", "TEST2"):
            return s
        hx, sd = f.get("other_bytes", {}).get(name), ref.get(key)
        if not hx or not sd:
            return None
        b, st_, dz = bytes.fromhex(hx), bytes.fromhex(sd["stock"]), bytes.fromhex(sd["design"])
        offs = [k for k in range(len(st_)) if st_[k] != dz[k]]
        if len(b) != len(st_):
            return None
        return "STOCK" if all(b[k] == st_[k] for k in offs) else "TARGET" if all(b[k] == dz[k] for k in offs) else "OTHER"
    ntsc_rec, pal_rec = by_design_bytes("stored_record", "stored_record_design"), by_design_bytes("pal_stored_record", "stored_record_design_pal")
    full = lambda x: x and x["of"] and (x["stock"] == x["of"] or x["design"] == x["of"])
    if pal_rec in ("STOCK", "TARGET") or full(d.get("stored_record_design_pal_bytes")):
        family = "PAL (mode 0x880's stored record is the 50 Hz one: 25p; use the PAL steps)"
    elif ntsc_rec in ("STOCK", "TARGET", "TEST", "TEST2") or full(d.get("stored_record_design_bytes")):
        family = "NTSC (mode 0x8c0's stored record is the 23.98p one: use the NTSC steps)"
    else:
        family = "not known from this result"
    one = lambda s: next(iter(s)) if len(s) == 1 else None
    pal_d = d.get("stored_record_design_pal_bytes")
    from_dump = not pal and pal_d and pal_d["of"] and pal_d["design"] == pal_d["of"]   # a dump: mode 0x880's cells are not read, its record is
    c_, p_, r_ = one(cells), one(pal) if pal else "TARGET" if from_dump else "STOCK", one(recs)
    sensor = {("STOCK", "STOCK", "STOCK"): "none (stock)",
              ("TARGET", "STOCK", "TARGET"): "L5 ogsq_fx2_v1 (NTSC squeeze)",
              ("TARGET", "STOCK", "TEST2"): "H5 ogh2560_fx2_v1 (NTSC real rows)",
              ("TEST", "STOCK", "TEST"): "B5 fhband_fx2_v1 (band test)",
              ("STOCK", "TARGET", "TARGET"): "Q5 ogsq880_fx2_v1 (PAL squeeze)",
              ("STOCK", "TARGET", "TEST2"): "P5 ogh2560880_fx2_v1 (PAL real rows)",
              ("TARGET", "STOCK", "K57"): "K5 og57n_fx2_v1 (NTSC 5.7K)",
              ("STOCK", "TARGET", "K57"): "J5 og57n880_fx2_v1 (PAL 5.7K)"}.get((c_, p_, r_))
    if sensor and from_dump and p_ == "TARGET":
        sensor += " (from mode 0x880's stored record and the picture records: a dump does not read mode 0x880's cells)"
    if sensor is None and not pal and c_ == "STOCK" and r_ in ("TARGET", "TEST2", "K57"):
        sensor = "the records of a PAL step (Q5/P5) with mode 0x8c0's cells stock: a PAL design, if this is a dump (the dump does not read mode 0x880's cells)"
    if sensor is None:
        sensor = "MIXED (cells %s, PAL cells %s, records %s)" % (sorted(x for x in cells if x), sorted(x for x in pal if x) or "-", sorted(x for x in recs if x))
    enc57 = None                                  # 2026-11-27: the 5.7K encoder side, named from the printed bytes
    for word, stt in ref.get("encoder_states", {}).items():
        if f.get("avcam_bytes") and f.get("avcam_bytes") == stt["av"] and f.get("libmpr_bytes") == stt["lm"]:
            enc57 = word
    encoder = ("applied (%s, 5.7K: %s)" % (enc57, ref["encoder_states"][enc57]["design"]) if enc57 else
               "applied (L19)" if f["avcam_target"] and not f["avcam_stock"] and not f["avcam_other"] else
               "stock" if f["avcam_stock"] and not f["avcam_target"] and not f["avcam_other"] else
               "not read" if not (f["avcam_stock"] or f["avcam_target"] or f["avcam_other"]) else
               "MIXED (%d stock, %d applied, %d other)" % (f["avcam_stock"], f["avcam_target"], f["avcam_other"]))
    raw = {st[k] for k in st if k.startswith("rawbuf_")}
    warn = None
    if (f["avcam_target"] or enc57) and sensor.startswith("none") and raw == {"STOCK"}:
        warn = ("WARNING: the encoder side (L19) is still applied but every coprocessor site is stock. This is what the FX2's power switch "
                "leaves: it restarts the image processor, not the main processor. Do not record in this state. Take the battery out for 10 "
                "seconds (everything stock), or run the putback, then apply again.")
    return {"family": family, "sensor_side": sensor, "encoder_side": encoder, "warning": warn, "stored_record_0x8c0": ntsc_rec, "stored_record_0x880": pal_rec}


def report(session, facts, which):
    f = facts["s3"]
    if which in WRITE_STEPS:
        lines = ["FX2 1.01 step %s: %s" % (which, f["what"]), "OUTCOME: %s" % f["outcome"], str(f["outcome_line"])] + ["  " + ln for ln in f["problem_lines"]]
        if f.get("text"):
            lines += ["the step's report:"] + ["  " + ln for ln in f["text"]]
        session.save_bytes("fx2_report.txt", ("\n".join(lines) + "\n").encode())
        for ln in lines:
            session.say(ln)
        return
    lines = ["FX2 1.01 %s, %s" % (which, time.strftime("%Y-%m-%d %H:%M:%S")), f["header"], f["verdict"],
             "identity: %d same, %d differ" % (f["identity_same"], f["identity_differs"]),
             "kernel: %s" % f["kernel_version"], "command line: %s" % f["kernel_command_line"]]
    for s in f["coprocessor_sites"]:
        lines.append("  coprocessor %-16s %s len %-4d %s%s" % (s["name"], s["address"], s["length"], s["state"], "" if s["shown"] is None else "  (" + s["shown"] + ")"))
    lines += ["  " + ln for ln in f["libmpr_sites"]] + ["  " + ln for ln in f["avcam_guards"]]
    lines.append("  av-cam.bin sites: %d stock, %d target, %d other" % (f["avcam_stock"], f["avcam_target"], f["avcam_other"]))
    lines += ["problem lines:"] + ["  " + ln for ln in f["problem_lines"]] if f["problem_lines"] else ["no problem lines"]
    cs = camera_state(f)                          # v5
    lines[3:3] = ["camera set to: %s" % cs["family"], "sensor side in place: %s" % cs["sensor_side"], "output size (4K class): %s" % output_size(f),
                  "encoder side: %s" % cs["encoder_side"]] + \
                 ([cs["warning"]] if cs["warning"] else [])
    d = f.get("decoded")
    if d:
        sr = d.get("sensor_registers")
        if sr:
            lines.append("sensor register shadow: closest matrix column %d (%d of %d rows equal; modes %s); register row 0 holds %d (column %d is the full-height read-out)"
                         % (sr["closest_column"], sr["rows_equal_per_column"][sr["closest_column"]], sr["rows"], ", ".join(sr["modes_using_it"]), sr["register_row0"], sr["full_height_column"]))
        lines.append("register matrix equals the file: %s" % d.get("matrix_equals_file"))
        zero = [m for m, v in d.get("stored_records", {}).items() if v["all_zero"]]
        same = [m for m, v in d.get("stored_records", {}).items() if not v["bytes_differing_from_emulation"]]
        lines.append("stored drive-parameter records: %d read, %d equal to the emulated ones, %d all zero" % (len(d.get("stored_records", {})), len(same), len(zero)))
        v = d.get("stored_records", {}).get("0x8c0")
        if v:
            lines.append("  mode 0x8c0: %d bytes differ from the emulation at %s" % (v["bytes_differing_from_emulation"], ", ".join(v["offsets"])))
        if d.get("stored_record_design_bytes"):
            lines.append("  mode 0x8c0, the design's %(of)d bytes: %(stock)d stock, %(design)d as the design" % d["stored_record_design_bytes"])
        if d.get("stored_record_design_pal_bytes"):          # v5
            lines.append("  mode 0x880 (PAL 25p), the PAL designs' %(of)d bytes: %(stock)d stock (50 Hz), %(design)d as the design" % d["stored_record_design_pal_bytes"])
        if d.get("size_table"):
            lines.append("movie size table: " + "; ".join("%dx%d id %#x" % tuple(r) for r in d["size_table"]))
        if d.get("raw_write_buffer_words"):
            lines.append("raw write buffer words (memory manager): %(stock)d stock, %(new)d applied, %(other)d other" % d["raw_write_buffer_words"])
        mm = d.get("memory_manager")
        if mm:
            lines.append("memory manager workspace %s (%s)" % (mm["workspace"], "decoded" if mm["as_expected"] else "NOT at the expected address: not decoded"))
            if mm.get("as_expected"):
                lines.append("  raw write buffer units seen (live or left over): %s" % mm["raw_write_buffer_units_seen"])
                for o in mm["live_objects"]:
                    if o["in_use"] or o["divided_as_group"]:
                        lines.append("  live: key %s size %d%s%s" % (o["key"], o["size"], ", open as %s" % o["opened_as"] if o["opened_as"] else "",
                                                                   ", divided as group %s" % o["divided_as_group"] if o["divided_as_group"] else ""))
                for o in mm["left_over_objects"][:30]:
                    lines.append("  left over: key %s size %d x %d" % (o["key"], o["size"], o["count"]))
                if mm["left_over_divisions"]:
                    lines.append("  left-over divisions: %s" % ", ".join(mm["left_over_divisions"][:20]))
        for r in d.get("output_records") or []:
            lines.append("output record %d: %dx%d, format code %d, type %d; picture %s bytes (at 3840x2560: %s; buffers 0x2d9 / 0x4c4 hold 13,271,040)"
                         % (r["record"], r["w"], r["h"], r["format_code"], r["type"], r["picture_bytes"], r["bytes_at_3840x2560"]))
        rv = d.get("resize_view")
        if rv:
            lines.append("resize view %s: flag bytes +4/+5 = %d/%d (%s); first stage %dx%d, crop %dx%d, first scaler %dx%d, output %dx%d, mode %s"
                         % (rv["address"], rv["flags"][4], rv["flags"][5], "the first-scaler size follows the output size" if rv["follows_output_size"] else "no override",
                            *rv["first_stage"], *rv["crop"], *rv["first_scaler"], *rv["output"], rv["mode"]))
            if "records_in_place" in rv:
                mode_ok = rv["mode"] in ("0x8c0", "0x880")       # the 4K 23.98p / 25p modes; another mode = the view of the last mode run (e.g. STILL)
                lines.append("  the picture records in place (%s) give a first scaler of %dx%d: %s"
                             % (rv["records_in_place"], *rv["first_scaler_by_records"],
                                "the view agrees" if rv["sizes_agree"] else
                                "the view is of mode %s, not the 4K movie mode (0x8c0 / 0x880): the camera was not on MOVIE at 4K when it was saved, "
                                "so the two are not compared" % rv["mode"] if not mode_ok else
                                # issue 5: with SteadyShot Active / Dynamic Active the view's first scaler is raised by a margin word (4336x2877
                                # and 5486x3658 for 2,560 rows) and the camera records clean 3840x2560 files; without a margin a difference was
                                # the L5 + L16 crash
                                "the view DIFFERS, by more than the output needs: a SteadyShot margin (%s), which runs on FX2s with og2560" % margin_name(rv)
                                if rv["first_scaler"][1] > max(rv["output"][1], rv["first_scaler_by_records"][1]) and rv["output"][1] <= rv["first_scaler_by_records"][1] else
                                "the view DIFFERS (the second scaler is handed a size the first scaler does not deliver; "
                                "the view may also be left from an earlier state)"))
        mw = d.get("margin_words")
        if mw:
            # Pull request 6, second version: the switch alone does not tell (SteadyShot Active applied 7208 with switch 3, GitHub issue 5),
            # so judge from the view: the override stores max(records' first scaler, output / (1 - margin)), so a margin is in use when the
            # view exceeds both.
            fs = rv and "records_in_place" in rv and (rv["first_scaler"][1], rv["output"][1], rv["first_scaler_by_records"][1])
            note = ("margin in use: the view asks the first scaler for %d rows for %d output rows, %.1f%% (%s)" % (fs[0], fs[1], 100.0 * (1 - fs[1] / fs[0]), margin_name(rv))
                    if fs and fs[0] > max(fs[1], fs[2])
                    else "no margin in use: the view's first scaler is no larger than the records or the output give" if fs
                    else "whether one is in use shows in the resize view")
            lines.append("resize margin words at %s: %s; switch %d (%s)"
                         % (mw["address"], ", ".join(str(x) for x in mw["words"]), mw["switch"], note))
        fh = next((x for x in f["coprocessor_sites"] if x["name"] == "fehold"), None)
        if fh:
            lines.append("fallback code word (fehold_fx2_v1) at %s: %s" % (fh["address"], fh["state"]))
        kr = d.get("kprint")
        if kr:
            if kr["exception"]:
                lines.append("kprint (kept across a restart without power loss): an EXCEPTION RECORD: task %s, %s, pc %s, lr %s, DFAR %s%s%s"
                             % (kr.get("task", "?"), kr.get("cause", "?"), ", ".join(kr["pcs"]), kr.get("lr", "?"), kr.get("dfar", "?"),
                                "; the forced 'S-Ele Refresh ng' exception (a pipeline stage still busy after 11 frames: the camera restarted)"
                                if kr["forced_refresh_exception"] else "", "; snapshot saved" if kr.get("snapshot_saved") else ""))
            else:
                lines.append("kprint: no exception record")
        sh = d.get("snapshot_head")
        if sh:
            # the area always holds some bytes (12,800 non-zero on a camera that never crashed in this power-on); only the tag marks a saved image
            lines.append("snapshot debug image at %s: %s; %d non-zero bytes in its first pages; first bytes %s"
                         % (sh["address"], "all zero" if sh["all_zero"] else "a SAVED SNAPSHOT (tag SOLID_SSHOT found: kept across a restart without power loss)"
                            if sh["tag_found"] else "no snapshot (no SOLID_SSHOT tag; the bytes there are other data)", sh["nonzero_bytes"], sh["first_bytes"][:48]))
            for s in (sh["strings"][:20] if sh["tag_found"] else []):
                lines.append("  snapshot string: %s" % s[:120])
        ss = d.get("scaler_state")
        if ss:
            lines.append("resize state (pages ported from the A7 IV's by code reference; the block's layout is not confirmed, so sizes are searched):")
            for k, v in ss.get("where_sizes_occur", {}).items():
                lines.append("  %s at %s%s" % (k, ", ".join(v[:10]), " ..." if len(v) > 10 else ""))
            if "resize_settings_0x190ea40" in ss:
                lines.append("  module settings 0x190ea40: %s" % ss["resize_settings_0x190ea40"])
        dp = d.get("display")
        if dp:
            lines.append("display (what the screen step changes):")
            if "panel_types" in dp:
                t = dp["panel_types"]
                lines.append("  panel types: rear %d (%s), viewfinder %d (%s)" % (t["rear_0x19d98cc"], t["rear_aspect"], t["viewfinder_0x19d99fc"], t["viewfinder_aspect"]))
            if "fit_16x9_picture" in dp:
                ft = dp["fit_16x9_picture"]
                lines.append("  a 16:9 picture: fit word on a 4:3 panel %d, on a 3:2 panel %d (3 letterbox, 0 fill)" % (ft["on_4x3_panel"], ft["on_3x2_panel"]))
            if "desqueeze_words" in dp:
                lines.append("  De-Squeeze Display ratio and crop words: %s" % dp["desqueeze_words"])
            if "screen_words" in dp:
                lines.append("  screen step words: %(stock)d stock, %(new)d applied, %(other)d other" % dp["screen_words"])
            for t, rw in dp.get("frame_rectangles_16x9_picture", {}).items():
                lines.append("  frame table %s: row 0 %s, row 1 %s, row 2 %s" % (t, rw["row0"], rw["row1"], rw["row2"]))
    session.save_bytes("fx2_report.txt", ("\n".join(lines) + "\n").encode())
    for ln in lines[:8] + lines[-6:]:
        session.say(ln)


def last_saved_sha():
    """The SHA-256 of the result the newest saved session of this kit fetched, or None."""
    root = c.PRIVATE_ROOT
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
        try:
            return json.loads((folder / "manifest.json").read_text(encoding="utf8"))["results"]["ct6"]["result"]["sha256"]
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=sorted(PINS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--remove-only", action="store_true")
    ap.add_argument("--clear-result", metavar="SHA256", help="first delete the result file of an earlier run from the RAM disk, only if its SHA-256 is this")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-memory", action="store_true", help="needed for a write step (%s): it changes the running camera's memory" % ", ".join(WRITE_STEPS))
    ap.add_argument("--writes-flash", action="store_true", help="needed besides --writes-memory for a start-up loader step that can write the camera's flash "
                    "(%s): a battery change does not undo it, the uninstall step W41 does" % ", ".join(LOADER_FLASH))
    a = ap.parse_args()
    if a.which in WRITE_STEPS and a.go and not (a.dry_run or a.selftest) and not a.writes_memory:
        raise SystemExit("%s is a write step: %s. It needs --writes-memory as well. Use fx2_apply.py. Nothing was sent." % (a.which, WRITE_STEPS[a.which][2]))
    if a.which in LOADER_FLASH and a.go and not (a.dry_run or a.selftest) and not a.writes_flash:
        raise SystemExit("%s can write the camera's FLASH: %s. A battery change does not undo that; the uninstall step (W41) does. "
                         "It needs --writes-flash as well. Use the start-up loader's launchers. Nothing was sent." % (a.which, WRITE_STEPS[a.which][2]))
    lib = use(a.which)
    if a.dry_run or a.selftest:
        if a.selftest:                              # --dry-run and --selftest win over --go (the launchers always pass --go): nothing is sent
            for line in selftest(lib):
                print("PASS  " + line)
            print("all checks passed; nothing was sent to any device")
        else:
            print("\n".join(R.dry_run_lines(lib)))
        return
    if not a.go or a.firmware_shown != FIRMWARE:
        raise SystemExit("A live run needs --go and --firmware-shown %s (the version the camera's menu shows). Nothing was sent." % FIRMWARE)
    R.refusals(lib)
    selftest(lib)                                   # the flow must pass on the simulated camera on the day, before the real one
    import ct1_stage2_service as service
    # A result left on the RAM disk by the run before stops a new run. Without --clear-result the newest result saved on this PC is named: the
    # runner deletes the camera's file only if its SHA-256 is that one, i.e. only a result already here.
    R.CLEAR_SHA = a.clear_result or last_saved_sha()
    body = R.body_remove_only if a.remove_only else R.body_run
    with c.Session("remove_only" if a.remove_only else "fx2_%s" % a.which, test="CT6") as session:
        session.results.update(firmware_shown_on_camera=a.firmware_shown, model=MODEL, which=a.which, library_sha256=PINS[a.which][1],
                               pc={"platform": platform.platform(), "python": sys.version.split()[0]})
        inner = service.connect(session)
        try:
            R.service_session(session, inner, lambda cam: body(session, cam, lib), lib)
            facts = session.results.get("ct6", {}).get("result")
            if facts and not a.remove_only:
                pages = facts.pop("_pages", {})
                for addr, (name, blob) in sorted(pages.items()):
                    session.save_bytes("cp_%s_%08x.bin" % (name, addr), blob)
                report(session, facts, a.which)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            print("Library sent: %s. On the camera now: %s." % (
                "yes" if out.get("library_sent") else "no",
                {False: "no (confirmed)", True: "YES", None: "not sent" if not out.get("library_sent") and not a.remove_only else "UNKNOWN"}[out.get("library_on_camera_after")]))
            if a.which in WRITE_STEPS:
                print("This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. The power switch alone does NOT: on the FX2 it puts the image processor's steps back but keeps the encoder step (L19), a mixed state not to record in (GitHub issue 5). Keep the camera on between steps; to undo, use the putback or take the battery out.")
            else:
                print("Nothing on the camera was changed. Unplug and replug the USB cable before another run; a cold boot (battery out) clears the result file.")


if __name__ == "__main__":
    main()
