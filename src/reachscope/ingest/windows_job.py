"""Own a Windows subprocess tree using a kill-on-close Job Object.

This local adapter uses the OS API rather than depending on process enumeration
or killing every Java process. POSIX callers use their own process group instead.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Any

logger = logging.getLogger(__name__)


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def apply_job_limits(limits: _ExtendedLimits, memory_limit_bytes: int) -> None:
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x100
    limits.ProcessMemoryLimit = memory_limit_bytes


class WindowsJob:
    """The handle's lifetime owns descendants even if the worker exits first."""

    def __init__(self, pid: int) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Objects are available only on Windows")
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise OSError("Windows process control API is unavailable")
        kernel: Any = loader("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError("Cannot create worker Job Object")
        self._kernel = kernel
        self._handle: Any = handle
        limits = _ExtendedLimits()
        apply_job_limits(limits, worker_memory_limit_bytes())
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError("Cannot configure worker Job Object")
        process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            self.close()
            raise OSError("Cannot open worker for process-tree ownership")
        try:
            if not kernel.AssignProcessToJobObject(handle, process):
                raise OSError("Cannot assign worker process to Job Object")
        except OSError:
            self.close()
            raise
        finally:
            kernel.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def worker_memory_limit_bytes() -> int:
    """Cap Windows committed memory at 4 GiB, POSIX address space at 8 GiB.

    JVM virtual reservations need more room than Windows committed memory.
    Operators may override either limit with REACHSCOPE_WORKER_MEMORY_MB.
    """
    default_limit = (4 if os.name == "nt" else 8) * 1024**3
    value = os.environ.get("REACHSCOPE_WORKER_MEMORY_MB")
    try:
        limit = int(value) * 1024 * 1024 if value is not None else default_limit
    except ValueError:
        logger.warning("Invalid REACHSCOPE_WORKER_MEMORY_MB; using %d MiB", default_limit // 1024**2)
        limit = default_limit
    if limit <= 0:
        logger.warning("Invalid REACHSCOPE_WORKER_MEMORY_MB; using %d MiB", default_limit // 1024**2)
        return default_limit
    return limit
