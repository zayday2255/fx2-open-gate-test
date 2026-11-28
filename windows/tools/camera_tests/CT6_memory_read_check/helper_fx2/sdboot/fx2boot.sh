#!/bin/sh
# FX2 1.01 start-up loader: the helper (2026-11-28). Run by the camera's own shell (busybox), as a process of its own:
#   busybox sh fx2boot.sh <folder> <power-on number | usb> <build> [now]
# started by the start-up hook once per power-on (folder /etc/fx2boot), or by the kit's "run now" step (folder /tmp_wbshd/fx2boot, "now").
#
# It runs the kit's own step libraries, the same files the kit sends over USB, in the kit's order, each in a small process of its own:
# the camera's loader loads the step library into `busybox true`, the library does its step as it does inside the camera application,
# and writes the kit's result file. After each step the result is read as the kit's runner reads it; the first step that is not DONE
# (or NOTHING TO DO) ends the run. Coprocessor transfers go through fx2cp.so, which stands in for the camera's libsencore.so there.
# The encoder steps are the kit's levels 19 and 20 built for a process outside the camera application (X19, X20): they reach the
# application's libmpr.so through /proc/<pid>/maps and /proc/<pid>/mem.
#
# When a plan cannot be finished, the encoder side is put back to stock (X20). The encoder side is the one part that outlives a
# switch-off with the battery in; with it in place and the rest stock the camera must not record (the kit's own warning).
#
# The kit leaves the result file of a session's last step on the RAM disk until its next session. The step libraries write that same
# file and do nothing while it exists, so the helper sets the kit's file aside for the length of its run and puts it back unchanged.
#
# It writes RAM only (/tmp_wbshd): its log, the step results, its busy mark. It touches no file on flash.
D=$1; N=$2; BUILD=$3; HOW=$4
R=/tmp_wbshd
LOG=$R/fx2boot.log
RES=$R/readcheck_result.txt
BUSY=$R/fx2boot.busy
KEPT=$R/fx2boot.kitresult                # the kit's own result file, set aside while the helper's steps run
FIRMWARE=45002_02.2025101101          # /version.txt of ILME-FX2 1.01
SETTLE=10                             # seconds between the camera application being found and the first step, at a power-on
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
BACK=                                 # the step that puts the encoder side back, once the plan is known to have one

say() { echo "fx2boot[$N]: $*" >> $LOG; }
restore() { [ -e $KEPT ] && [ ! -e $RES ] && mv $KEPT $RES; }
finish() { restore; say "END: $*"; rm -f $BUSY; exit 1; }
stop() { say "$*"; finish "nothing more is done"; }

# One step: load the library into a small process, keep its result, set OUT to DONE, NOTHING, READ or a word for "not done".
step() {
    S=$1
    L=$D/libJit_fx2_$S.so
    F=$R/fx2boot_$S.txt
    OUT=absent
    [ -f $L ] || { say "$S: $L is absent"; return 1; }
    OUT=busy
    [ -e $RES ] && { say "$S: a result file appeared (a kit session over USB?): it is left alone"; return 1; }
    case $S in
        X21) LD_PRELOAD="$D/fx2cp.so $L" /bin/busybox true ;;     # the kit's check, outside the application: it reads the coprocessor
        X*) LD_PRELOAD="$L" /bin/busybox true ;;                  # encoder side: no coprocessor transfer
        *) LD_PRELOAD="$D/fx2cp.so $L" /bin/busybox true ;;
    esac
    RC=$?
    OUT=none
    [ -f $RES ] || { say "$S: the step left no result (exit $RC)"; return 1; }
    mv $RES $F
    OUT=cut
    grep -q "^== done" $F || { say "$S: the result is not complete (kept in $F)"; return 1; }
    if [ "$2" = read ]; then
        # a read step reports its verdict; the two lines before it say whether the camera application was found and what its
        # identity lines gave, so a NOT READY can be read without the result file
        OUT=READ; say "$S: read; `grep -i -m1 'verdict' $F`"
        grep -m1 -e '^!! ' $F | sed 's/^/    /' >> $LOG
        grep -m1 '^file ' $F | sed 's/^/    /' >> $LOG
        return 0
    elif grep -q "UNDO INCOMPLETE" $F; then
        OUT=undo; say "$S: UNDO INCOMPLETE: take the battery out for 10 s before anything else (kept in $F)"; return 1
    elif grep -q "^DONE: " $F; then
        OUT=DONE; say "$S: `grep -m1 '^DONE: ' $F`"; return 0
    elif grep -q "^NOTHING TO DO" $F; then
        OUT=NOTHING; say "$S: `grep -m1 '^NOTHING TO DO' $F`"; return 0
    fi
    OUT=refused
    say "$S: not done: `grep -m1 -e '^NOT DONE' -e '^!!' $F` (kept in $F)"
    return 1
}

# The plan did not finish: the encoder side goes back to stock, unless that cannot be judged safe (a result in the way, an undo that failed).
give_up() {
    case "$BACK:$OUT" in
        :*|*:busy|*:undo) finish "the plan was not finished" ;;
    esac
    say "the plan was not finished: the encoder side is put back to stock ($BACK)"
    if step $BACK; then finish "the plan was not finished; the encoder side is stock"; fi
    finish "the plan was not finished, and the encoder side could not be put back: do not record; take the battery out for 10 s"
}

[ -d $R ] || exit 1
# the log is kept small: it is RAM
[ -f $LOG ] && [ `wc -c < $LOG` -gt 60000 ] && tail -c 20000 $LOG > $LOG.new && mv $LOG.new $LOG
say "START build $BUILD, files in $D"
# one helper at a time: the busy mark holds the time it was made; one older than five minutes is a leftover
NOW=`date +%s`
if [ -f $BUSY ]; then
    T=`cat $BUSY`
    case "$T" in ''|*[!0-9]*) T=0 ;; esac
    if [ $((NOW - T)) -lt 300 ] && [ $((NOW - T)) -ge 0 ]; then say "another helper is at work ($BUSY is there)"; say "END: nothing is done"; exit 1; fi
    say "a busy mark older than five minutes is ignored"
fi
echo $NOW > $BUSY
# Marks of earlier power-ons, and their step results. The hook's own mark (/tmp_wbshd/fx2boot.mark, the uptime of the boot that last
# started a helper) is NOT removed here: the next boot compares against it to tell "a new boot" from "another program of this one".
for f in $R/fx2boot.g*; do rm -f "$f"; done
rm -f $R/fx2boot_*.txt

[ -f /version.txt ] || stop "/version.txt is not there"
[ "`cat /version.txt`" = "$FIRMWARE" ] || stop "the camera's firmware is not the one this build was made for (/version.txt)"

# ---- the SD card as the on/off switch (2026-11-27). Measured on an FX2, card in then out: /dev/mmcb1 (a formatted card: whole device plus
# first partition) is there exactly when a card is in, and /dev/mmcb (any card) likewise; /dev/mmcb-char is there either way because it is
# the slot's controller, so it must NOT be the test. Nothing else in /dev or /sys/block changes with the card. The usual names
# (/sys/block/mmcblk0, /sys/bus/mmc) do not exist on this camera, which is why the block nodes are tested directly.
# Only a power-on run is gated: "run now" over USB is an explicit command from an operator, who can see the camera.
if [ "$HOW" != now ]; then
    if [ -e /dev/mmcb1 ]; then
        say "SD card present (/dev/mmcb1): the switch is on"
    elif [ -e /dev/mmcb ]; then
        say "SD card present (/dev/mmcb, no partition yet): the switch is on"
    else
        stop "no SD card (/dev/mmcb1 and /dev/mmcb are absent): the switch is off, nothing is applied"
    fi
fi

[ -f $D/plan ] || stop "no plan is chosen ($D/plan is absent)"
PLAN=`cat $D/plan`
case "$PLAN" in
    check) STEPS="X21" ;;                            # read-only: the kit's check built for a process outside the application (X21)
    og2560) STEPS="L13 H5 L16 X19 S16" ;;            # 3840x2560 open gate, 23.98p/24p (the kit's og2560)
    og2560pal) STEPS="L13 P5 L16 X19 S16" ;;         # the same on a PAL-set camera, 25p (the kit's og2560 --pal)
    squeeze) STEPS="X20 L13 L5 S16" ;;               # the squeezed open gate (the kit's squeeze): its encoder side is the stock one
    og57) STEPS="L13 K5 K16 X22 S16" ;;              # 5.7K, 5760x3840 at 300 Mbps, 23.98p/24p (the kit's og57)
    og57pal) STEPS="L13 J5 K16 X22 S16" ;;           # 5.7K on a PAL-set camera, 25p (the kit's og57 --pal)
    *) stop "the plan file does not hold a plan of this build" ;;
esac
say "plan $PLAN: $STEPS"

# the camera application: exactly one process named im.elf
i=0
while :; do
    PID=`pidof im.elf`
    case "$PID" in
        '') ;;
        *' '*) stop "more than one process is named im.elf ($PID)" ;;
        *) break ;;
    esac
    i=$((i + 1))
    [ $i -ge 30 ] && stop "the camera application (im.elf) was not found in 30 s"
    sleep 1
done
if [ "$HOW" = now ]; then say "camera application: process $PID"; sleep 3; else say "camera application: process $PID; waiting $SETTLE s"; sleep $SETTLE; fi
# the kit's last result (of an earlier session, or of the "run now" step that started this): aside for now, back at the end
restore
if [ -e $RES ]; then
    [ -e $KEPT ] && stop "two result files of the kit are there ($RES and $KEPT): they are left alone"
    mv $RES $KEPT || stop "the kit's result file could not be set aside"
    say "the kit's result file is set aside for this run"
fi

if [ "$PLAN" = check ]; then
    for S in $STEPS; do step $S read || stop "the read-only plan stopped at $S"; done
    restore
    say "END: plan check, every step done"
    rm -f $BUSY
    exit 0
fi
# The step that puts the encoder side back, once the plan is known to have one. It must match the plan's own encoder step: X20 puts back
# the 4K design (og2560, og2560pal) and X23 the 5.7K one (og57, og57pal); the squeeze plan's encoder side is the stock one, so it is X20.
case $PLAN in
    og57|og57pal) BACK=X23 ;;
    *) BACK=X20 ;;
esac
for S in $STEPS; do step $S || give_up; done
restore
say "END: plan $PLAN, every step done"
rm -f $BUSY
exit 0
