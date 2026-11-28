"""EMULATION ONLY: a process that stands in for the camera application in the test sandbox (emu_fx2boot.py).

It names itself im.elf, maps a copy of the camera's libmpr.so the way the dynamic loader maps a library's text (private, read + execute, from
file offset 0), prints the mapping's address, and sleeps. The loader's "outside" steps must find it by name, find the mapping in
/proc/<pid>/maps, and read and write the bytes through /proc/<pid>/mem: the real kernel does the rest, as on the camera.
Further files (the other libraries the read-only check looks for in the application's list of mappings) are mapped the same way.
With FAKE_IM_MEMORY=<file> the mapping's MEMORY is made to hold that file's bytes while libmpr.so on disk stays as it is: a camera whose
encoder side is applied (the application's memory is changed, the file it was loaded from is not).

  python3 fake_im.py <libmpr.so> [name] [more files to map ...]
"""
import ctypes
import mmap
import os
import sys
import time

path = sys.argv[1]
name = (sys.argv[2] if len(sys.argv) > 2 else "im.elf").encode()
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl(15, ctypes.c_char_p(name), 0, 0, 0)                     # PR_SET_NAME
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]


def map_file(p, memory=None):
    fd = os.open(p, os.O_RDONLY)
    n = os.fstat(fd).st_size
    a = libc.mmap(None, n, mmap.PROT_READ | (mmap.PROT_WRITE if memory else mmap.PROT_EXEC), mmap.MAP_PRIVATE, fd, 0)
    if a in (None, ctypes.c_void_p(-1).value):
        raise SystemExit("mmap failed")
    if memory:                                                      # private pages: the file on disk is not touched
        b = open(memory, "rb").read()
        if len(b) != n:
            raise SystemExit("the memory file is not the library's size")
        ctypes.memmove(a, b, n)
        libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        if libc.mprotect(a, n, mmap.PROT_READ | mmap.PROT_EXEC):
            raise SystemExit("mprotect failed")
    return a, n


for extra in sys.argv[3:]:
    map_file(extra)
addr, size = map_file(path, os.environ.get("FAKE_IM_MEMORY"))
print("%d %x %d" % (os.getpid(), addr, size), flush=True)
while True:
    time.sleep(3600)
