"""Read available system commit/physical memory without changing OS settings."""

import ctypes
import os
from ctypes import wintypes


def memory_headroom():
    if os.name != "nt":
        return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ("physical_total", "physical_available",
                "commit_total", "commit_available", "virtual_total", "virtual_available", "extended_virtual")]
    status = MemoryStatus();status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Unable to read system memory status")
    return {"physical_available": status.physical_available, "commit_available": status.commit_available,
            "physical_total": status.physical_total, "commit_total": status.commit_total}


def require_headroom(min_commit_bytes=1073741824):
    status = memory_headroom()
    if status and status["commit_available"] < min_commit_bytes:
        raise MemoryError("System commit headroom below safe checkpoint threshold")
    return status
