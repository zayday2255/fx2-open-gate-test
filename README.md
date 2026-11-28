# FX2 open gate: test kit (firmware 1.01)

<p><b>New (2026-11-27, issue #7): a 5760 × 3840 (5.7K) test and XAVC S-I 4K, on NTSC and PAL. Not yet run on an FX2</b>: please try <code>open_gate_5760x3840_test</code> (PAL: <code>open_gate_5760x3840_pal</code>), see "5.7K and XAVC S-I".</p>

<p><b>The true 3840 × 2560 open gate works on the FX2, on NTSC and on PAL (issue #5, 2026-11-26/27).</b> <code>open_gate_3840x2560_test</code> records 3840 × 2560 files of the whole 3:2 sensor area in XAVC HS 4K and XAVC S 4K at 23.98p. On a camera set to PAL, <code>open_gate_3840x2560_pal</code> records them in XAVC S 4K at 25p (see "PAL"). Two warnings from issue #5: <b>test 6 is a diagnostic step only, do not record in it</b> (the camera froze), and <b>the power switch does not undo the patch</b> (it leaves half of it applied: use the battery or the putback). This kit ports the open gate that works on the A7 IV to the Sony FX2 (ILME-FX2) firmware 1.01. The patch only writes to the camera's memory.</p>

**Where it stands (2026-11-27):**

- **The true 3840 × 2560 open gate works on an FX2 set to NTSC (2026-11-26, issue #5).** `open_gate_3840x2560_test` (L13 + H5 + L16 + L19 + S16), applied from a cold boot:
  - XAVC HS 4K and XAVC S 4K, HEVC/AVC 4:2:2 10-bit, **3840 × 2560**, 23.976p. A 10-minute clip (7.4 GiB, past the 4 GB mark) decodes with no error. Audio, timecode and Sony's per-frame metadata track are kept.
  - Rows outside the stock 16:9 band show no step or banding; both base ISOs (800 and 4000 EI) work, also when switched during a recording.
  - MediaInfo and DaVinci Resolve read 3:2 from the file. In-camera playback works.
  - The 3:2 rear screen is filled, round things look round, touch focus lands on the subject near the edges too. De-Squeeze Display 1.3x gives about 1.95:1 and 2.0x 3:1 with the whole frame.
  - HDMI works: the whole 3:2 frame, squeezed into 1080p 16:9. Remote control from a monitor (REC, white balance, shutter) works, and the patch survives a switch to PC Remote and back.
  - **Field of view:** a frame of the 3840 × 2560 clip and a full-sensor still (taken with the patch applied; stills still work) have the same framing, within about 2%. The file holds the whole 3:2 sensor area.
  - **SteadyShot Active works** with the patch: a steady picture, clean 3840 × 2560 clips, cropped about 1.12–1.15× as Active usually crops. The dump shows the camera raising the first scaler's request by its 11% margin (4336 × 2877); unlike the old L5 + L16 crash, it keeps running.
- **Test 5 works; test 6 froze the camera on REC** (issue #5, another FX2). That is expected now: in test 6 the encoder is still set for 2,160 rows. **Test 6 is a diagnostic step only: do not record in it.** For clips use `open_gate_3840x2560_test`.
- **The power switch keeps half of the patch** (issue #5). After switching off and on, every image-processor step (raw buffer, sensor, output size, screen) was stock again, but the main processor still held the encoder step. That mixed state is not safe to record in. Undo with a battery pull (10 seconds) or `open_gate_putback_3840x2560`. The check now says which state the camera is in and warns about this one.
- **PAL works (fifth kit, issue #5).** On a camera set to PAL, 4K 25p uses a different video mode (0x880) whose stored settings come from the 50 Hz table, so the NTSC sensor steps (L5, H5) refuse there and write nothing. The PAL steps **P5** (real rows) and **Q5** (squeeze) are H5 and L5 moved to mode 0x880. On an FX2 set to PAL:
  - `open_gate_3840x2560_pal` records XAVC S 4K **3840 × 2560 at 25.000 fps**, 3:2 in MediaInfo, every frame clean; SteadyShot Active works too. The dump on MOVIE shows the same state as NTSC's, in mode 0x880.
  - `open_gate_squeezed_pal` records the squeezed 3840 × 2160 file.
  - The check names the camera PAL by itself, a wrong-family launcher refuses, and the power-switch warning fires on PAL too. Face/Eye AF and tracking stay on the face up to the edges of the 3:2 frame.
  - On a PAL FX2, XAVC HS 4K is 50p only, so PAL means **XAVC S 4K 25p**.
- **More from issue #5 (NTSC):** Proxy Recording works (the proxy holds the whole 3:2 picture squeezed into 16:9), SteadyShot **Dynamic Active** works (cropped about 1.43×), and XAVC S takes Dynamic Active and proxy at once.
- **Do not change the frame rate while it is applied.** Switching 24p to 60p restarted the camera (the known forced exception). It is harmless, and everything is stock again afterwards, the encoder step included.

- **First FX2 test (2026-11-25, issue #1).** Every step applied and read back on the camera: raw buffer, sensor, output size, encoder and screen. The USB route, the read-only checks and the macOS launchers all work on the FX2.
  - **The failure.** Entering MOVIE gave a purple flash, then the image processor stopped itself and the camera restarted, with the patch gone. This happened four times, also without the screen step.
  - **What the crash record says.** The code at 0x507da0 prints "FW: S-Ele Refresh ng force exception" and stops on purpose when a stage of the picture pipeline is still busy after 11 frames. That is exactly what the A7 IV did before its raw write buffer was enlarged (its F662/F667). This kit's first step enlarges that buffer, so something else on the FX2 is still in the way. We cannot tell what from the record.
  - **Read on the camera:** rear panel type 3 (3:2), viewfinder type 2 (4:3).
- **Test 2 works (2026-11-26).** L13 + L5 only, on MOVIE: a steady picture, no restart, and two clips recorded (HEVC 3840 × 2160 4:2:2 10-bit, 23.98p; the picture is the whole sensor height, squeezed into 16:9, as on the A7 IV).
  - The dump on MOVIE: sensor in its full-height mode (register column 5), the stage the whole 7008 × 4672 window, the stored record as designed, and the raw write buffer in use at 33,003,520 bytes (the enlarged one).
  - So the full-height read-out, the enlarged buffer and the squeeze all work on the FX2, and **the crash of the full apply comes from L16 (output size) or L19 (encoder)**. The FX6 kit's bisection points the same way (its L16).
  - What the firmware shows: the FX2 chooses each output's buffer by its picture size. It has an output kind the A7 IV lacks, with a small fixed buffer, and at 3840 × 2560 some format codes would not fit the 13,271,040-byte buffers. The camera's own output records tell which applies: the dump now reads them.
- **Test 3 crashes; the squeezed open gate works (2026-11-26).** L13 + L5 + L16 crashes on MOVIE entry with the same forced exception, with or without the encoder step, in 4:2:2 and 4:2:0. So L16 (the output size) is the first failing step. L13 + L5 + S16 (`open_gate_squeezed`, a tester's pull request) runs and records.
- **Why L16 crashed** (read from the FX2's code, then emulated; `PORT_NOTES.md`):
  - It is not the output buffer. The camera's four output records are 3840 × 2160, 1920 × 1080, 1920 × 1080 and 3840 × 2160, all with format code 2, as on the A7 IV. A 3840 × 2560 picture is then 12,288,000 bytes and fits the 13,271,040-byte buffer. (The third kit read these records at a wrong address and showed zeros; the pages it saved hold them.)
  - The FX2's resize set-up has a step the A7 IV lacks. After it reads the first scaler's picture size from the mode's records (4336 × 2438), it raises that size to at least the output size. With L16 it becomes 4336 × 2560, while the records still make the first scaler deliver 2,438 rows. The second scaler is told to expect rows that never come.
  - Of the bodies we have firmware for, only the FX2 and the A1 II have that step. On the A7 IV, FX3 and A7S III the second scaler simply enlarges the picture.
  - Run alone in emulation, the set-up gives byte for byte the values the tester's camera saved, in the stock state and in the working squeezed state.
- **Fourth kit: the fix to test.** The A7 IV already has a design whose first scaler gives 4336 × 2560 (`ogh2560_v1`, it works there). It is ported as step **H5** and takes L5's place. With it the two sizes agree, and the file's 2,560 rows are real rows. A fallback (**F16**, one code word that keeps the first-scaler size) is in the kit for the case that H5 does not run.
  - The read-only dump now shows the resize set-up's saved sizes and whether they agree with the records in place.
  - `open_gate_apply` is unchanged and **still crashes on the FX2**: do not use it.
- **Built and emulated.** Every step was checked against the FX2 1.01 firmware's own files and code (Unicorn), and every library was run against a model FX2 (`PORT_NOTES.md`).
- **Why it should work.** The FX2 has the A7 IV's sensor:
  - the same video modes (plus two the A7 IV lacks);
  - the same sensor tables and register matrix;
  - the same stored records for every mode the two share, from the FX2's own calculator.

  Its image processor is the A7C II's newer build of the same software. On the A7 IV these steps record a true 3840 × 2560 file in XAVC HS 4K and XAVC S 4K, with MP4 headers that DaVinci Resolve opens at 3:2.
- **The shape of the kit is the FX3 kit's** (`fx3-open-gate-test`, which records open gate on two FX3s): the same launchers, the read-only check before any write, the closing read-only session, Windows, macOS and Android.
- **One step more than the FX3 kit:** the raw write buffer. The FX2's movie raw write buffer holds the stock 16:9 read-out only (7040 × 3958). A full-height read-out needs 4,688 rows, as on the A7 IV, so step 1 enlarges it.
- **No playback step.** The FX2 opens movie playback the A7 IV's way (its 8K decoder channel), and the A7 IV plays its own 3840 × 2560 clips. So in-camera playback should work, but it has not been tried (see "While it is applied").

**What it does.** A true 3840 × 2560 (3:2) recording in XAVC HS 4K and XAVC S 4K at 23.98p (NTSC), or in XAVC S 4K at 25p (PAL), set in the camera's memory only. A battery pull removes it. New, not yet run on an FX2: a 5760 × 3840 (5.7K) state and XAVC S-I 4K (see "5.7K and XAVC S-I").

**Kits cannot be mixed up.** The FX3, A7S III and ZV-E1 kits' check libraries say NOT READY on an FX2. This kit's check says NOT READY on an A7 IV, an A7C II or an FX3. Every write step writes nothing unless each byte it changes holds exactly the FX2 1.01 stock value. All of this was checked in emulation.

| Launcher | What it does | Writes to the camera? |
|---|---|---|
| `check_readonly.cmd` | Confirms the camera runs the 1.01 software the port was made from and reads what every patch site holds. Verdict READY / NOT READY | No |
| `dump_info.cmd` | The same, plus facts for the port: memory map, the camera's own logs, sensor register state, internal tables, the memory manager's records, the display (panel type, fit word, frame tables, de-squeeze words) | No |
| `open_gate_apply.cmd` | Applies the A7 IV's default state in five steps: raw write buffer, sensor, output size, encoder (with the MP4 headers), then the rear screen at 3:2 with De-Squeeze Display set for it. **Crashes on MOVIE entry on the FX2: use `open_gate_squeezed.cmd` or the fourth kit's tests** | **Yes: memory only** |
| `open_gate_apply_no_screen.cmd` | Only the four open-gate steps | **Yes: memory only** |
| `open_gate_apply_no_meta.cmd` | The default state with the encoder step that leaves the MP4 headers at 3840 × 2160 | **Yes: memory only** |
| `open_gate_putback.cmd` | Puts the five steps back | Yes: memory only |
| `screen_putback.cmd` | Puts the screen step back | Yes: memory only |
| `test1_fullheight_band.cmd` | **Diagnostic test 1** (second kit): raw write buffer + full-height sensor read-out with the stock 16:9 picture, then one read-only dump on MOVIE | **Yes: memory only** |
| `test2_squeeze_only.cmd` | **Diagnostic test 2** (second kit): raw write buffer + the full-height sensor step only, then one read-only dump on MOVIE. **Works on the FX2** | **Yes: memory only** |
| `open_gate_squeezed.cmd` | **Squeezed open gate** (ran on an FX2, 2026-11-26): raw write buffer + full-height sensor step + rear-screen step, then one read-only dump on MOVIE. A 3840 × 2160 file holding the whole 3:2 sensor area squeezed 27/32 vertically (stretch the height by 32/27 in the editor); the rear screen shows it at 3:2. No output-size or encoder step | **Yes: memory only** |
| `test3_output_size.cmd` | **Diagnostic test 3** (third kit): test 2 + the output size (3840 × 2560), then one read-only dump on MOVIE | **Yes: memory only** |
| `test4_output_size_encoder.cmd` | **Diagnostic test 4** (third kit): test 3 + the encoder side (the open gate without the screen step), then one read-only dump on MOVIE | **Yes: memory only** |
| `test5_real_rows.cmd` | **Test 5** (fourth kit): raw write buffer + the sensor step H5 (first scaler 4336 × 2560), then one read-only dump on MOVIE. Works on an FX2 | **Yes: memory only** |
| `test6_real_rows_output_size.cmd` | **Test 6** (fourth kit): test 5 + the output size (3840 × 2560), then one read-only dump on MOVIE. **Diagnostic only: do not press REC** (the camera froze) | **Yes: memory only** |
| `open_gate_3840x2560_test.cmd` | **The 3840 × 2560 open gate** (fourth kit): raw write buffer, sensor step H5, output size, encoder (with the MP4 headers), rear screen, then one read-only dump on MOVIE. **Works on an FX2 set to NTSC.** On a camera set to PAL it takes the PAL step (as the newest check reads the camera, or it asks) | **Yes: memory only** |
| `open_gate_3840x2560_pal.cmd` | **The same for a camera set to PAL** (fifth kit): raw write buffer, PAL sensor step P5 (mode 0x880, 25p), output size, encoder, rear screen. **Works on an FX2 set to PAL** (XAVC S 4K 25p) | **Yes: memory only** |
| `open_gate_squeezed_pal.cmd` | The squeezed open gate for a camera set to PAL (fifth kit): raw write buffer, PAL sensor step Q5, rear screen. Works on an FX2 set to PAL | **Yes: memory only** |
| `open_gate_putback_3840x2560.cmd` | Puts the 3840 × 2560 open gate back without a battery pull (NTSC or PAL) | Yes: memory only |
| `open_gate_5760x3840_test.cmd` | **5.7K test** (issue #7): a 5760 × 3840 file, 300 Mbps on the 100M and higher settings. NTSC: XAVC HS 4K or XAVC S 4K 23.98p; a PAL-set camera takes the PAL step. Not yet run on an FX2 | **Yes: memory only** |
| `open_gate_5760x3840_pal.cmd` | The 5.7K test for a camera set to PAL: XAVC S 4K 25p. Not yet run on an FX2 | **Yes: memory only** |
| `open_gate_putback_5760x3840.cmd` | Puts the 5.7K state back without a battery pull | Yes: memory only |
| `open_gate_3840x2560_si_test.cmd` | The 3840 × 2560 open gate **plus XAVC S-I 4K** (one more encoder step). The S-I step is not yet run on an FX2 | **Yes: memory only** |
| `open_gate_5760x3840_si_test.cmd` | The 5.7K test **plus XAVC S-I 4K**. Not yet run on an FX2 | **Yes: memory only** |
| `open_gate_putback_3840x2560_si.cmd`, `open_gate_putback_5760x3840_si.cmd` | Put the S-I states back without a battery pull | Yes: memory only |
| `test7_frontend_hold.cmd` | **Test 7, the fallback** (fourth kit): raw write buffer, sensor step L5, one code word that keeps the first-scaler size (F16), output size, encoder. Only if test 5 gives no picture. Not yet run on an FX2 | **Yes: memory only** |
| `macos/arm_open_gate.command` (macOS only) | **Arm, then plug in** (a tester's addition, 2026-11-26): asks the Mac password once, waits up to 15 minutes for the FX2, and the moment it connects runs the read-only check and the 3840 × 2560 steps (L13, H5, L16, L19, S16) **in one USB connection** (`fx2_batch.py`). Nothing is written unless that check, in the same connection, says VERDICT READY for an ILME-FX2 1.01. A notification says Done. Ran on an FX2 1.01: check + 5 steps DONE in a 6.9 s session, 3840 × 2560 clips | **Yes: memory only** |
| `macos/open_gate_fast.command` (macOS only) | The same one-connection run, started by hand with the camera already plugged in | **Yes: memory only** |

Nothing in this kit writes to the camera's firmware or to its settings.

## Before you start

1. The camera's menu must show **Ver. 1.01**. On any other version, stop and tell us the version.
2. **USB Connection Mode: Mass Storage.**
3. A charged battery. Do not record or play back while a step runs.
4. **The Still/Movie switch** on the FX2 chooses stills or movie. Below, "STILL" and "MOVIE" mean the switch's two positions.

## Windows, once

1. Install Python 3.10 or later from python.org (with the "py launcher").
2. Run `windows/setup.cmd`.
3. Install the libusb-win32 driver for the camera with [Zadig](https://zadig.akeo.ie): Options, List All Devices, pick the camera, choose libusb-win32, Replace Driver. The first run switches the camera to service mode, where it shows up as a new device (054C:0336 on the other bodies): install the driver for that one too, then run the step again.

## macOS, once (ran with an FX2 on 2026-11-25)

The macOS kit is the A7 IV kit's macOS port, carried over unchanged apart from the launcher names. It runs the same scripts as Windows (`windows/tools`).

1. Python 3.9 or later: the one macOS offers with the Xcode Command Line Tools (run `xcode-select --install` in Terminal) works, or install it from python.org.
2. Double-click `macos/setup.command`. It sets up Python and the USB library the scripts use. No Homebrew and no driver are needed.
3. Each Windows launcher has a macOS twin with the same name: `macos/check_readonly.command`, `dump_info.command`, `open_gate_apply.command`, `open_gate_apply_no_screen.command`, `open_gate_apply_no_meta.command`, `open_gate_putback.command`, `screen_putback.command`, `test1_fullheight_band.command`, `test2_squeeze_only.command`, `test3_output_size.command`, `test4_output_size_encoder.command`, `open_gate_squeezed.command`, `test5_real_rows.command`, `test6_real_rows_output_size.command`, `open_gate_3840x2560_test.command`, `open_gate_3840x2560_pal.command`, `open_gate_squeezed_pal.command`, `open_gate_putback_3840x2560.command`, `open_gate_5760x3840_test.command`, `open_gate_5760x3840_pal.command`, `open_gate_putback_5760x3840.command`, `open_gate_3840x2560_si_test.command`, `open_gate_5760x3840_si_test.command`, `open_gate_putback_3840x2560_si.command`, `open_gate_putback_5760x3840_si.command`, `test7_frontend_hold.command`. Everything below that says `.cmd` works the same with the `.command` file. (The first FX2 tester ran the macOS launchers: they work.)

**Quit Lightroom, Photos and Image Capture before you run the kit.** They take hold of the camera's card; Lightroom froze a tester's FX2 on "Accessing".

Each live run asks for your Mac password: macOS keeps its own driver on the camera's USB connection, and only an administrator can hand the camera over to the script. The script unmounts the camera's memory card first; it does not erase anything on it. The results go to the same `windows/camera_private` folder.

If macOS refuses to open a .command file ("unidentified developer" or "could not verify"), open System Settings > Privacy & Security, scroll down and click "Open Anyway". Or open Terminal, type `bash` and a space, drag the .command file into the window, and press Return.

## Android (not run on a phone or camera yet)

`android/FX2-OpenGate.apk` runs this kit from a phone connected to the camera by USB-C (or an OTG adapter). It carries exactly the files in `windows/tools` of this commit and runs them unchanged; only the USB access, the dialogs and the folder for the results are the phone's.

1. Install the APK (allow installing from unknown sources). It installs beside the A7 IV, A7S III and FX3 apps; they do not share anything on the phone.
2. Set the camera as for the PC (below), and also **USB Power Supply: Off**, or it charges from the phone.
3. **1. Read-only check** first: the apply starts only after a check on this phone said READY. Then **2. Apply to camera**. The "Screen step" box chooses between the five-step apply (ticked) and the four open-gate steps only.
4. When Android asks to open *FX2 Open Gate* for the camera, tick **Always** and press OK. It comes up twice: once in Mass Storage, once in service mode.
5. When the log says **unplug and plug in again**, do that with the phone cable. Never switch the camera off.
6. **Stop waiting** ends a wait for the camera. It never interrupts a step that is talking to the camera.
7. Afterwards, **Export logs** writes a zip to `Download/FX2-OpenGate/` on the phone: send that zip back.

**Test 1: band**, **Test 2: squeeze**, **Test 3: + output size** and **Test 4: + encoder** run the diagnostic tests; like the apply, they start only after a check on this phone said READY. App 0.4 adds **Squeezed open gate (works)**, **Test 5: real rows**, **Test 6**, **3840x2560** and **Test 7: fallback** (the fourth kit). App 0.5 adds **3840x2560 PAL (25p)**, **Squeezed PAL (25p)** and **Put back 3840x2560** (the fifth kit). If the newest check cannot tell NTSC from PAL, the app asks. App 0.6: the closing dump asks you to confirm that the switch is on MOVIE. App 0.7 adds **5.7K (NTSC)**, **5.7K PAL (25p)**, **Put back 5.7K**, **3840x2560 + S-I** and **5.7K + S-I** (issue #7; not yet run on an FX2).

**Self-test** and **Dry run** need no camera and send nothing.

## The read-only steps

Each launcher asks for the firmware version the menu shows. Each run makes a new folder in `windows/camera_private`.

- **Check or dump in the stills state:** switch on STILL, connect, run the launcher.
- **Dump of the 4K state:** set File Format XAVC S 4K (or XAVC HS 4K) at 24p, S&Q off, APS-C/Super 35 off. Set MOVIE, record a few seconds, stop. **Stay on MOVIE**, connect, run `dump_info.cmd`.

What they do to the camera: they switch it to service mode, write one small program file to the service partition, which the camera loads once, and delete that file again in the same session. The program only reads and creates one file, its report, on the camera's RAM disk. Its source is `windows/tools/camera_tests/CT6_memory_read_check/helper_fx2/fx2read.c`.

## The diagnostic tests

The first test showed that the whole kit applies but the FX2 cannot run the result. These tests split it, as was done on the A7 IV. **Test 2 works on the FX2** (2026-11-26). Now please run, each from a cold boot: **test 2 again** (its dump now reads the camera's output records: their size, format code and kind), then **test 3**, then **test 4**. Test 1 is no longer needed.

| Test | Launcher | What it applies | The A7 IV did | If the FX2 runs it | If the FX2 crashes |
|---|---|---|---|---|---|
| 1 | `test1_fullheight_band.cmd` | raw write buffer; the sensor in the same full-height mode as the full kit, but the picture keeps the stock 16:9 band (so the pipeline's stage keeps its stock height) | a normal 16:9 picture and clip (F658) | the full-height read-out works; the dump shows which write buffer the camera opened, and its size | the FX2 does not take the sensor's full-height mode itself |
| 2 | `test2_squeeze_only.cmd` | raw write buffer + the full kit's sensor step, nothing else (no output size, encoder or screen step) | a squeezed 16:9 picture of the whole sensor height (F682) | **seen on the FX2 (2026-11-26)**: the problem is in the output-size or encoder step | the problem is in the taller stage (4,688 rows) |
| 3 | `test3_output_size.cmd` | test 2 + the output size: the picture the pipeline delivers becomes 3840 × 2560 | the picture stayed squeezed on the screen, and a recording stopped by itself after a second, because the encoder was still set for 2160 rows (F688) | the output size is fine; run test 4 | the output size is the problem (the dump of test 2 tells which buffer) |
| 4 | `test4_output_size_encoder.cmd` | test 3 + the encoder side | a true 3840 × 2560 file (F698) | the open gate works without the screen step; a clip is 3840 × 2560 | the encoder side, or its combination with the output size, is the problem |

**How to run each test**

1. Set File Format XAVC S 4K (or XAVC HS 4K) at 24p, APS-C/Super 35 off, S&Q off, Proxy off, De-Squeeze Display off.
2. Set the switch to STILL, pull the battery for 10 seconds, put it back and switch on. Do not go to MOVIE yet.
3. Connect USB (Mass Storage) and run `windows/check_readonly.cmd`: VERDICT READY.
4. Run the test's launcher. It asks for the firmware version and a typed YES, and runs two steps with a replug between them.
5. When it asks: **unplug, set MOVIE, watch the rear screen for ten seconds.**
   - **If there is a steady picture:** press REC, record about five seconds, stop.
   - **If the camera restarts by itself:** do not pull the battery; wait until it is on again and leave the switch on MOVIE.
6. **Plug in again** (choose Mass Storage if asked). The script runs the read-only dump by itself.
7. Write down what the screen did: a picture (its shape?), purple flashing, a restart?
8. Battery out for 10 seconds before the next test.

**Please send** the zipped `windows/camera_private` folder and, for each test, what the screen did. If a test recorded, add the clip or its properties.

## The fourth kit: the path to a true 3840 × 2560 file

Run these in order, each from a cold boot. Stop at the first one that restarts the camera and send the folders: the dump after the restart holds the crash record.

| Test | Launcher | What it applies | Expected | If the camera restarts |
|---|---|---|---|---|
| 5 | `test5_real_rows.cmd` | raw write buffer + sensor step H5: the first scaler gives 4336 × 2560 instead of 4336 × 2438; the output size stays stock | what test 2 gives: a steady picture, squeezed 3840 × 2160 clips | the FX2 does not take the taller first-scaler picture; run test 7 |
| 6 | `test6_real_rows_output_size.cmd` | test 5 + the output size 3840 × 2560 | a steady picture. **Do not press REC**: the encoder is still set for 2,160 rows, and on an FX2 a recording froze the camera until the battery was pulled (issue #5) | our reading of the crash is incomplete; the dump shows the sizes the camera worked with |
| 3840 × 2560 | `open_gate_3840x2560_test.cmd` | test 6 + the encoder side (with the MP4 headers) + the rear screen | **clips of 3840 × 2560** holding the whole 3:2 sensor area; the 3:2 rear screen filled. **Seen on an FX2 (issue #5)** | the encoder side is the problem |
| 7 | `test7_frontend_hold.cmd` | raw write buffer, sensor step L5, the code word F16, output size, encoder side | clips of 3840 × 2560 (2,438 rows enlarged to 2,560, as on the A7 IV); the rear screen shows the picture squeezed | both routes fail; send the folders |

**Settings for these tests:** File Format XAVC HS 4K (or XAVC S 4K) at 23.98p, **SteadyShot Off** for a first run, APS-C/Super 35 off, S&Q off, Proxy off, De-Squeeze Display off. With `open_gate_3840x2560_test` applied, SteadyShot Active, Dynamic Active and Proxy Recording have worked too (issue #5).

Run each as in "How to run each test" above (cold boot on STILL, `check_readonly`, the launcher, MOVIE when it asks, replug). The 3840 × 2560 test has five steps with a replug between them.

**Please send** the zipped `windows/camera_private` folder and, for each test, what the screen did. For a clip: its size as MediaInfo shows it, and whether a recording stopped by itself. In-camera playback of 3840 × 2560 clips works on an FX2; if a clip ever says "Unable to display", do not try again.

## 5.7K and XAVC S-I (issue #7, 2026-11-27; not yet run on an FX2)

**5.7K** is the A7 IV's real 5760 × 3840 state, ported step by step. On the A7 IV it records 5760 × 3840 files with real detail, at 300 Mbps, with I and P pictures only (no duplicate frames), and MP4 headers that say 5760 × 3840.

| Step | NTSC | PAL | What |
|---|---|---|---|
| 1 | L13 | L13 | the raw write buffer (as for 3840 × 2560) |
| 2 | **K5** (`og57n_fx2_v1`) | **J5** (`og57n880_fx2_v1`) | the full-height sensor read-out, with records that make the first scaler give 5760 × 3840 |
| 3 | **K16** (`og57cp_fx2_v3`) | K16 | four scaler units, a 30.8 MB buffer for the output picture (id 0x43f), the output size 5760 × 3840 |
| 4 | **K19** (`ogfile57r300m1_fx2_v4`) | K19 | the encoder side: two encoder cores, 300 Mbps on the 100M and higher settings, I and P pictures only, the MP4 headers at 5760 × 3840 |
| (4) | with `--no-meta`: M19 (`ogfile57r300m1_fx2_v3`) | M19 | the same, but the MP4 headers keep 3840 × 2160 |
| 5 | S16 | S16 | the rear screen at 3:2 (the same step as for 3840 × 2560) |

What was checked for the FX2 in particular, in emulation against the FX2's own code:
- **The FX2's first-scaler override** (the cause of the old L16 crash) asks for no more than K5's records give: 5760 × 3840 on both sides, NTSC and PAL.
- **The output buffer:** a 5760 × 3840 picture is 27.6 MB, more than the 13.3 MB buffers. The FX2 asks for id 0x43f above that size, and the stock FX2 has no such buffer. K16 makes 0x43f a 30.8 MB unit, the A7 IV's fix. In the FX2's own memory manager it opens, and the other 4K movie buffers still open beside it.
- **Four scaler units:** the FX2's split rule is the A7C II's and reads its setting byte at 0x18f62e8. Every FX2 dump so far reads that byte and its neighbours as zero, as K16 expects.
- Each step writes nothing unless every byte it changes holds the FX2 1.01 stock value, and refuses the other family's state.

**How to run it:** as the 3840 × 2560 test (cold boot on STILL, `check_readonly`, the launcher, MOVIE when asked, replug).
- **NTSC:** XAVC HS 4K or XAVC S 4K at 23.98p. **PAL:** XAVC S 4K at 25p.
- **SteadyShot Off**, APS-C/Super 35 off, S&Q off, Proxy off.
- **A V90 SD card or CFexpress Type A**: the 100M and higher settings record at 300 Mbps. The lower settings keep their bit rate.
- Record a short clip and check it on a computer: MediaInfo should show 5760 × 3840. 5.7K clips do not play back in the camera (on the A7 IV they never did). Don't retry playback.

**XAVC S-I 4K** (issue #7 found that S-I stops REC at once with the 3840 × 2560 patch, because the encoder step covers only XAVC HS and XAVC S). `open_gate_3840x2560_si_test` and `open_gate_5760x3840_si_test` add one encoder step for XAVC S-I 4K (AVC intra 4:2:2 10-bit): **I19** at 3840 × 2560, **G19** at 5760 × 3840. On the A7 IV the 5.7K S-I state records at 24p; the 3840 × 2560 one was never run there. With the S-I step applied, XAVC HS and XAVC S still record as before.

**Please send** the zipped `windows/camera_private` folder, MediaInfo's size, frame rate and bit rate for a clip, and what the rear screen showed.

## PAL (fifth kit; works on an FX2, 2026-11-26)

The menu's **NTSC/PAL Selector** decides the frame rates: NTSC gives 23.98p, PAL gives 25p. The two use different video modes inside the camera, so the sensor step comes in two forms. Every other step is the same.

| | NTSC (23.98p) | PAL (25p) |
|---|---|---|
| Video mode inside the camera | 0x8c0 | 0x880 |
| Sensor step, real rows (3840 × 2560 file) | H5 (`ogh2560_fx2_v1`) | **P5** (`ogh2560880_fx2_v1`) |
| Sensor step, squeeze (3840 × 2160 file) | L5 (`ogsq_fx2_v1`) | **Q5** (`ogsq880_fx2_v1`) |
| Raw buffer, output size, encoder, screen | L13, L16, L19, S16 | the same |

- A step of the wrong family checks the camera's stored mode record first, finds bytes it does not expect, and **writes nothing**. A PAL camera's dumps showed this for L5 and H5. The PAL steps refuse on an NTSC camera the same way. All of this was run in emulation on that PAL camera's own memory pages.
- The read-only check (fx2read_v5) now reads the video mode 0x880's sites too. Its report says "camera set to: NTSC" or "PAL" and which sensor step is in place.
- The apply launchers pick the family by themselves from your newest check. If that check cannot tell, they ask. `open_gate_3840x2560_pal` and `open_gate_squeezed_pal` say PAL outright.

**How to run it on PAL**

1. NTSC/PAL Selector: PAL. File Format **XAVC S 4K, 25p** (on a PAL FX2, XAVC HS 4K is 50p only). APS-C/Super 35 off, S&Q off, De-Squeeze Display off. SteadyShot Off for a first run; Active works too.
2. Switch to STILL, pull the battery for 10 seconds, put it back and switch on.
3. Connect USB and run `check_readonly`: VERDICT READY, and "camera set to: PAL".
4. Run `open_gate_3840x2560_pal`. It works like the NTSC test: five steps with a replug between them, then one read-only dump on MOVIE (it asks you to confirm the switch is on MOVIE first).
5. Record at 25p. MediaInfo shows 3840 × 2560 and 25 fps.

If the 3840 × 2560 state misbehaves on your camera, `open_gate_squeezed_pal` (from a cold boot) leaves out the output-size and encoder steps and records the squeezed 3840 × 2160 file. Reports of long recordings (heat) are welcome.

## The write steps

**What they change.** Five groups of bytes in the running camera's memory, one per step:

1. **Raw write buffer** (4 words of the image processor's memory manager): the movie raw write buffer holds 4,688 rows instead of 3,958, enough for the full sensor height (the A7 IV's `dmmwb4688_v1`).
2. **Sensor** (11 table cells, the two 4K picture records, 31 bytes of the stored mode record): full sensor height instead of the 16:9 band, kept whole and squeezed into the stock 4K picture (the A7 IV's `ogsq_v3`).
3. **Output size** (one word): 3840 × 2160 becomes 3840 × 2560.
4. **Encoder** (101 + 6 sites): the encoder's tables for XAVC HS 4K and XAVC S 4K at 23.98p and 25p, and the two height values the MP4 writer puts in the file's headers, 2160 → 2560 (the A7 IV's `ogfile2560_hs_s_v2`). `open_gate_apply_no_meta.cmd` leaves the headers at 2160.
5. **Screen** (18 words):
   - the 16:9 live view fills the 3:2 rear screen (it holds the whole sensor area, so it is shown at its true 3:2 shape, as on the A7 IV);
   - the focus and tracking frames are told where the picture now is;
   - De-Squeeze Display's shapes are set for the 3:2 picture (below).

Each step first checks that every byte it is about to change holds its stock value, writes, reads back, and undoes its own writes if anything does not match. `open_gate_apply_no_screen.cmd` runs only the first four.

**De-Squeeze Display** (Sony's own feature, in the menu's Display Option; on 1.01 it offers Off, 1.3x and 2.0x). The camera works out each shape for a 16:9 picture. With the open-gate picture, which is 3:2, every shape would be about 18% off, so step 5 gives it the shapes of the 3:2 frame:

| Setting | Stock FX2, 16:9 picture | With this kit, the 3:2 open-gate picture |
|---|---|---|
| 1.3x | 2.31:1 | **1.95:1** |
| 2.0x | 2.67:1 (the centre 4:3 of the frame) | **3:1: the whole frame** (the centre crop is turned off) |

It changes only the preview, not the recorded file. The firmware also has 1.65x and 1.8x shapes, which the 1.01 menu never selects; they are set for the 3:2 picture as well (2.47:1, 2.7:1).

**What we know now, and what not yet.**

- **The whole sensor height is in the file** (issue #5): a frame of a 3840 × 2560 clip and a full-sensor still have the same framing within about 2%.
- **The raw write buffer step** refuses while the movie memory is laid out the stock way. On the A7 IV it never is, after a cold boot with the camera on stills. The FX2 should be the same.
- **The power switch** (known since issue #5): it does NOT undo the patch on the FX2. It restarts the image processor, so the raw buffer, sensor, output-size and screen steps are stock again, but the encoder step stays. Do not record in that state. Undo with a battery pull or a putback.
- **The rear panel** is 3:2: the first test's dump read type 3 (viewfinder: type 2, 4:3).
- **Exposure, autofocus, long recordings, heat:** the sensor reads 18% more rows per frame. A 10-minute clip recorded without an overheat warning (issue #5).
- **PAL:** works (XAVC S 4K 25p, issue #5).
- **A frame-rate or format change while it is applied** restarts the camera (the known forced exception, harmless): everything is stock again afterwards.

**While it is applied**

- Use only XAVC HS 4K or XAVC S 4K at 24p (23.98p) on NTSC, or XAVC S 4K at 25p on PAL. Other 4K formats, frame rates, S&Q and APS-C/Super 35 are not set up and are likely to fail. **Do not change the frame rate while it is applied**: the camera restarts by itself and is back to stock (harmless, but the patch is gone).
- SteadyShot Off, Active and Dynamic Active, and Proxy Recording, all work with `open_gate_3840x2560_test` (issue #5). The proxy holds the whole 3:2 picture squeezed into 16:9.
- On the rear screen every 16:9 picture takes the 3:2 shape, and De-Squeeze Display uses the 3:2 shapes, so other movie formats look wrong there. The viewfinder (a 4:3 panel) keeps the squeezed picture, as on the A7 IV. HDMI gives the whole 3:2 frame squeezed into 1080p 16:9 (issue #5).
- **In-camera playback** of 3840 × 2560 clips works on an FX2 (issue #5). If a clip ever says "Unable to display", **do not try again**: on an FX3 a second try froze the camera.
- **Do not use the power switch to undo it**: see "The power switch" above.

**How to run it**

1. In the menu, set File Format XAVC S 4K (or XAVC HS 4K) and 24p. APS-C/Super 35 off, S&Q off. De-Squeeze Display Off for now. Set Proxy Recording to Off.
2. Set the switch to STILL. Then pull the battery for 10 seconds and switch on, so that nothing of an earlier run is left. Do not go to MOVIE yet.
3. Connect USB and run `windows/check_readonly.cmd`. It must say VERDICT READY.
4. Run `windows/open_gate_apply.cmd`. It starts only if your newest saved check or dump says READY. It asks for the firmware version and for a typed YES.
5. It runs five steps. Between steps it asks you to **unplug and replug the USB cable. Do not switch the camera off and do not pull the battery** until the script says it is finished.
6. After the five steps the script asks for one more session, which only reads. **Unplug USB, set MOVIE, look at the screen, and plug in again.** The script then runs the read-only dump by itself and prints the rear panel's type.
7. When it says so, unplug. The rear screen should show the whole picture at 3:2.
8. Record 20 to 30 seconds and stop. Check the clip on a computer. Then try De-Squeeze Display at 1.3x and 2.0x.
9. To return to stock: battery out for 10 seconds, or `open_gate_putback.cmd`.

**If the camera restarts by itself** at any point: do not pull the battery. Set the switch to STILL, connect USB, run `windows/dump_info.cmd`, and only then pull the battery for 10 seconds. The image processor keeps its own log across a restart without power loss, and the dump reads it.

**Please send back**

- The zipped `windows/camera_private` folder, with the closing dump of the apply in it.
- The clip, or its properties: size, frame rate, codec. Do the same with XAVC S 4K if you can.
  - **Field of view:** a still photo of the same scene from a tripod, so we can see whether the clip has the whole sensor height.
  - **MediaInfo:** `mediainfo --Output="Video;%Width%x%Height% original %Width_Original%x%Height_Original%" FILE` should give 3840x2560 with no "original" size. ffprobe cannot show the header change: it reads the size from the stream.
  - **Editors:** whether Resolve or Premiere opens the original file at 3:2.
- The rear screen with De-Squeeze Display Off, 1.3x and 2.0x: a phone photo with something round in the picture helps.
- Whether the focus and tracking frames sit on the subject with De-Squeeze Display Off.
- Your settings: file format and record setting, frame rate, NTSC or PAL, SteadyShot, Log shooting.

**If the camera misbehaves** (grey lines, flicker, restart, freeze, recording that stops by itself): do not pull the battery straight away if the camera still responds. Set STILL, connect USB, run `dump_info.cmd`, and send the folder. Then pull the battery for 10 seconds. If the camera does not respond at all, just pull the battery. `open_gate_apply_no_screen.cmd` applies open gate without the screen step.

**If the apply stops part-way:** it says at which step. Pull the battery for 10 seconds to be sure of the camera's state, and send the folder. If step 1 (raw write buffer) refuses, the camera was probably on MOVIE since it was switched on: battery out, switch on STILL, and run it again.

**To remove only the screen step:** set STILL and run `windows/screen_putback.cmd`.

## Open gate at power-on, without a computer (experimental; not yet run on an FX2)

`SDBOOT.md` describes a start-up loader that applies the 3840 × 2560 open gate by itself when the camera is switched on on STILL. It grew out of a tester's research branch; that page also says, in short, where that first attempt was stuck and why.

- It is tested in emulation only. Its launchers are `loader_*` in `windows/` and `macos/`.
- `loader_try_readonly` and `loader_try_open_gate` write nothing to flash: a battery change removes everything they did. Start with those, in that order.
- `loader_install_*` **writes the camera's flash**. A battery change does not undo it; `loader_uninstall` does.
- The phone app does not have these steps.

## If something stops

Every stop prints a reason and "Nothing was sent" or what was sent. Please send that text. Common ones:

- *the camera is in service mode but that device has no libusb driver yet*: expected on the first run. Do the Zadig step for the new device and run again.
- *DeviceInfo.xml is not the file of the 1.01 update*: another firmware or model. Nothing further is sent.
- *DIFFERS from the 1.01 update* in a check: not an FX2 on 1.01 (an A7 IV, A7C II or FX3 gives this too). The apply will not start.
- *a libJit.so is already on the service partition*: a session broke half-way. Replug, and run the same step with `--remove-only`.
- *!! read failed -21* (ten times) in an S16 step: harmless. That step copies `/proc/driver/pcie/*`, which are folders.
- *!! truncated at 2048 bytes* in a dump: harmless. The dump copies only the first 2,048 bytes of each of the camera's log files; the rest is left out on purpose.
- *WARNING: the encoder side (L19) is still applied but every coprocessor site is stock*: the state the power switch leaves. Pull the battery for 10 seconds (or run `open_gate_putback_3840x2560`), then apply again.
- *the newest check (…) reads this camera as PAL* (or NTSC) when you gave the other one: set the NTSC/PAL Selector the way you want, run `check_readonly` again, then the apply.

## What is in here

- `windows/`: the launchers, `setup.cmd`, and `tools/`:
  - the scripts, the pinned program files and their source;
  - the patch designs of every step;
  - the builders and emulations of the designs (`tools/modding/fx2`).
- `macos/`: `setup.command` and one `.command` launcher per Windows launcher; they run `windows/tools`.
- `android/FX2-OpenGate.apk`: the phone app, carrying `windows/tools` as published here.
- `PORT_NOTES.md`: how the A7 IV kit maps onto the FX2, what was checked and how, and what is not known.
- `SDBOOT.md`: the experimental start-up loader; its sources, builds and offline tests are in `windows/tools/camera_tests/CT6_memory_read_check/helper_fx2/sdboot`.

Built on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) (vendored under `windows/tools/third_party`, MIT licence).
