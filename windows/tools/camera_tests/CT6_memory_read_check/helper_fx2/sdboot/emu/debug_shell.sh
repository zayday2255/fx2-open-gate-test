#!/usr/bin/env bash
# EMULATION ONLY: run one command line with the camera's shell in the test sandbox that emu_fx2boot.py left in ~/a7iv/fx2boot_emu/root
# (for looking at a failed check). With TRACE=1 qemu prints every system call of every program to stderr.
#   bash debug_shell.sh 'ls -la /etc/fx2boot'
set -u
S="$HOME/a7iv/fx2boot_emu/root"
exec unshare -r -m bash -c '
  S=$1; shift
  mount -t binfmt_misc none /proc/sys/fs/binfmt_misc || exit 1
  MAGIC="\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00"
  MASK="\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff"
  printf "%s" ":qemu-aarch64:M::${MAGIC}:${MASK}:$(command -v qemu-aarch64):FP" > /proc/sys/fs/binfmt_misc/register || exit 1
  mount --rbind /proc "$S/proc"; mount --bind /dev/null "$S/dev/null"
  if [ "${TRACE:-0}" = 1 ]; then export QEMU_STRACE=1; fi
  PATH=/sbin:/bin:/usr/sbin:/usr/bin HOME=/ chroot "$S" /bin/busybox sh -c "$1"
' dbg "$S" "$1"
