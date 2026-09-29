from __future__ import annotations

import ctypes
import gc
import sys


def release_cpu_memory() -> None:
    """Return freed native allocations to the OS when running on glibc."""
    gc.collect()
    # CDLL(None) is a POSIX operation; on Windows it raises TypeError.
    # Native memory trimming is optional and must not fail model cleanup.
    if sys.platform != "linux":
        return
    try:
        libc = ctypes.CDLL(None)
        malloc_trim = libc.malloc_trim
        malloc_trim.argtypes = [ctypes.c_size_t]
        malloc_trim.restype = ctypes.c_int
        malloc_trim(0)
    except (AttributeError, OSError):
        # malloc_trim is a glibc extension and is unavailable on some platforms.
        pass
