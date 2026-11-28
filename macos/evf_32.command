#!/bin/bash
# FX2 1.01 (LOCAL, 2026-11-28): the viewfinder at 3:2, after an open gate apply: E16 makes De-Squeeze Display 1.3x show 1.5:1, so with
# 1.3x set the 4:3 viewfinder shows the whole open-gate frame at its true 3:2 shape (and the rear screen stays 3:2). Display only.
# It refuses unless the screen step S16 is in place. Use E16 or A16 (desqueeze_15x), not both: they change the same two words.
# Camera on STILL or MOVIE, USB in (Mass Storage). Undo: E17 (back to 1.95:1) or a cold boot (battery out 10 s, USB unplugged).
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" run E16 --go --writes-memory --firmware-shown 1.01 "$@"
