from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.container_runtime import is_containerized
from utils.timezone import beijing_now


_PROCESS_STARTED_MONOTONIC = time.monotonic()
_PROCESS_STARTED_AT = beijing_now().isoformat(timespec="seconds")
_NETWORK_SAMPLE: tuple[float, int, int] | None = None
_PROCESS_CPU_SAMPLE: tuple[float, float] | None = None
_RUNTIME_SNAPSHOT_TTL_SECONDS = 1.0
_RUNTIME_SNAPSHOT_LOCK = threading.Lock()
_RUNTIME_SNAPSHOT_CAPTURED_AT = 0.0
_RUNTIME_SNAPSHOT_CACHE: dict[str, Any] | None = None
_WINDOWS_IF_TYPE_LOOPBACK = 24
_WINDOWS_IF_OPER_STATUS_OPERATIONAL = 5
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_MAX_REASONABLE_CGROUP_LIMIT = 1 << 60


def _read_linux_memory() -> tuple[int, int] | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return None
    values: dict[str, int] = {}
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            name, separator, raw_value = line.partition(":")
            if not separator:
                continue
            parts = raw_value.strip().split()
            if not parts:
                continue
            values[name] = int(parts[0])
    except (OSError, ValueError):
        return None
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if total <= 0 or available is None:
        return None
    total_bytes = total * 1024
    available_bytes = available * 1024
    return total_bytes, max(0, total_bytes - available_bytes)


def _read_windows_memory() -> tuple[int, int] | None:
    if os.name != "nt":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        total = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return total, max(0, total - available)


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _read_non_negative_int(path: Path) -> int | None:
    raw_value = _read_text(path)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value >= 0 else None


def _read_cgroup_memory() -> tuple[int, int] | None:
    candidates = (
        (_CGROUP_ROOT / "memory.max", _CGROUP_ROOT / "memory.current"),
        (
            _CGROUP_ROOT / "memory" / "memory.limit_in_bytes",
            _CGROUP_ROOT / "memory" / "memory.usage_in_bytes",
        ),
        (
            _CGROUP_ROOT / "memory.limit_in_bytes",
            _CGROUP_ROOT / "memory.usage_in_bytes",
        ),
    )
    for limit_path, used_path in candidates:
        raw_limit = _read_text(limit_path)
        if raw_limit in (None, "max"):
            continue
        try:
            limit = int(raw_limit)
        except ValueError:
            continue
        used = _read_non_negative_int(used_path)
        if not 0 < limit < _MAX_REASONABLE_CGROUP_LIMIT or used is None:
            continue
        return limit, used
    return None


def _read_memory(*, containerized: bool) -> tuple[int | None, int | None, str]:
    system_memory = _read_windows_memory() if os.name == "nt" else _read_linux_memory()
    if containerized:
        cgroup_memory = _read_cgroup_memory()
        if cgroup_memory is not None and (
            system_memory is None or cgroup_memory[0] <= system_memory[0]
        ):
            return cgroup_memory[0], cgroup_memory[1], "container"
        if system_memory is not None:
            return system_memory[0], system_memory[1], "visible"
        return None, None, "visible"
    if system_memory is None:
        return None, None, "system"
    return system_memory[0], system_memory[1], "system"


def _read_cgroup_cpu_quota() -> float | None:
    cpu_max = _read_text(_CGROUP_ROOT / "cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
            except ValueError:
                pass
            else:
                if quota > 0 and period > 0:
                    return quota / period

    candidates = (
        (
            _CGROUP_ROOT / "cpu" / "cpu.cfs_quota_us",
            _CGROUP_ROOT / "cpu" / "cpu.cfs_period_us",
        ),
        (
            _CGROUP_ROOT / "cpu.cfs_quota_us",
            _CGROUP_ROOT / "cpu.cfs_period_us",
        ),
    )
    for quota_path, period_path in candidates:
        quota = _read_non_negative_int(quota_path)
        period = _read_non_negative_int(period_path)
        if quota and period:
            return quota / period
    return None


def _read_cpu_capacity(*, containerized: bool) -> float:
    capacities = [float(max(1, os.cpu_count() or 1))]
    get_affinity = getattr(os, "sched_getaffinity", None)
    if callable(get_affinity):
        try:
            affinity_count = len(get_affinity(0))
        except OSError:
            affinity_count = 0
        if affinity_count > 0:
            capacities.append(float(affinity_count))
    if containerized:
        quota = _read_cgroup_cpu_quota()
        if quota is not None and quota > 0:
            capacities.append(quota)
    return round(max(0.01, min(capacities)), 2)


def _distribution_name() -> str:
    system = platform.system() or "Unknown"
    if system.lower() == "linux":
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            release = {}
        pretty_name = str(release.get("PRETTY_NAME") or "").strip()
        if pretty_name:
            return pretty_name
        name = str(release.get("NAME") or system).strip()
        version = str(release.get("VERSION_ID") or "").strip()
        return " ".join(part for part in (name, version) if part) or system
    if system.lower() == "darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}".strip()
    release = platform.release()
    return " ".join(part for part in (system, release) if part) or "Unknown"


def _read_linux_process_memory() -> int | None:
    status = Path("/proc/self/status")
    if not status.is_file():
        return None
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            name, separator, raw_value = line.partition(":")
            if name.strip() != "VmRSS" or not separator:
                continue
            value = int(raw_value.strip().split()[0])
            return max(0, value * 1024)
    except (IndexError, OSError, ValueError):
        return None
    return None


def _read_windows_process_memory() -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return None
        return max(0, int(counters.WorkingSetSize))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _read_process_memory() -> int | None:
    return _read_windows_process_memory() if os.name == "nt" else _read_linux_process_memory()


def _read_process_cpu_percent(cpu_capacity: float) -> float | None:
    global _PROCESS_CPU_SAMPLE
    now_wall = time.monotonic()
    now_cpu = time.process_time()
    previous = _PROCESS_CPU_SAMPLE
    _PROCESS_CPU_SAMPLE = (now_wall, now_cpu)
    if previous is None:
        return None
    elapsed_wall = now_wall - previous[0]
    elapsed_cpu = now_cpu - previous[1]
    if elapsed_wall <= 0 or elapsed_cpu < 0:
        return None
    return round(
        max(0.0, min(100.0, elapsed_cpu * 100 / elapsed_wall / cpu_capacity)),
        1,
    )


def _read_linux_network_bytes() -> tuple[int, int] | None:
    network = Path("/proc/net/dev")
    if not network.is_file():
        return None
    received = 0
    transmitted = 0
    try:
        for line in network.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            interface, raw_values = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            values = raw_values.split()
            if len(values) < 9:
                continue
            received += int(values[0])
            transmitted += int(values[8])
    except (OSError, ValueError):
        return None
    return received, transmitted


def _read_windows_network_bytes() -> tuple[int, int] | None:
    if os.name != "nt":
        return None

    class MibIfRow(ctypes.Structure):
        _fields_ = [
            ("wszName", ctypes.c_wchar * 256),
            ("dwIndex", wintypes.DWORD),
            ("dwType", wintypes.DWORD),
            ("dwMtu", wintypes.DWORD),
            ("dwSpeed", wintypes.DWORD),
            ("dwPhysAddrLen", wintypes.DWORD),
            ("bPhysAddr", ctypes.c_ubyte * 8),
            ("dwAdminStatus", wintypes.DWORD),
            ("dwOperStatus", wintypes.DWORD),
            ("dwLastChange", wintypes.DWORD),
            ("dwInOctets", wintypes.DWORD),
            ("dwInUcastPkts", wintypes.DWORD),
            ("dwInNUcastPkts", wintypes.DWORD),
            ("dwInDiscards", wintypes.DWORD),
            ("dwInErrors", wintypes.DWORD),
            ("dwInUnknownProtos", wintypes.DWORD),
            ("dwOutOctets", wintypes.DWORD),
            ("dwOutUcastPkts", wintypes.DWORD),
            ("dwOutNUcastPkts", wintypes.DWORD),
            ("dwOutDiscards", wintypes.DWORD),
            ("dwOutErrors", wintypes.DWORD),
            ("dwOutQLen", wintypes.DWORD),
            ("dwDescrLen", wintypes.DWORD),
            ("bDescr", ctypes.c_ubyte * 256),
        ]

    try:
        iphlpapi = ctypes.windll.iphlpapi
        get_if_table = iphlpapi.GetIfTable
        get_if_table.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.BOOL,
        ]
        get_if_table.restype = wintypes.DWORD
        size = wintypes.ULONG(0)
        result = get_if_table(None, ctypes.byref(size), False)
        if result not in (0, 122) or size.value < ctypes.sizeof(wintypes.DWORD):
            return None
        buffer = (ctypes.c_byte * size.value)()
        if get_if_table(ctypes.byref(buffer), ctypes.byref(size), False) != 0:
            return None
        entry_count = int(ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value)
        row_size = ctypes.sizeof(MibIfRow)
        first_row_offset = ctypes.sizeof(wintypes.DWORD)
        max_entries = max(0, (size.value - first_row_offset) // row_size)
        received = 0
        transmitted = 0
        for index in range(min(entry_count, max_entries)):
            row = MibIfRow.from_buffer_copy(buffer, first_row_offset + index * row_size)
            if (
                row.dwType == _WINDOWS_IF_TYPE_LOOPBACK
                or row.dwOperStatus != _WINDOWS_IF_OPER_STATUS_OPERATIONAL
            ):
                continue
            received += int(row.dwInOctets)
            transmitted += int(row.dwOutOctets)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return received, transmitted


def _read_network_bytes() -> tuple[int, int] | None:
    return _read_windows_network_bytes() if os.name == "nt" else _read_linux_network_bytes()


def _network_rates() -> tuple[float | None, float | None]:
    global _NETWORK_SAMPLE
    counters = _read_network_bytes()
    if counters is None:
        return None, None
    now = time.monotonic()
    previous = _NETWORK_SAMPLE
    _NETWORK_SAMPLE = (now, counters[0], counters[1])
    if previous is None:
        return None, None
    elapsed = now - previous[0]
    if elapsed <= 0:
        return None, None
    received_delta = counters[0] - previous[1]
    transmitted_delta = counters[1] - previous[2]
    if os.name == "nt":
        # GetIfTable exposes 32-bit interface counters. Account for a single
        # counter rollover between two dashboard samples.
        if received_delta < 0:
            received_delta += 1 << 32
        if transmitted_delta < 0:
            transmitted_delta += 1 << 32
    return (
        round(max(0.0, received_delta / elapsed), 1),
        round(max(0.0, transmitted_delta / elapsed), 1),
    )


def _storage_percent(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return round(max(0.0, min(100.0, usage.used * 100 / usage.total)), 1)


def _nullable_round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _percentage(used: int | None, total: int | None) -> float | None:
    if used is None or total is None or total <= 0:
        return None
    return round(max(0.0, min(100.0, used * 100 / total)), 1)


def _capture_snapshot() -> dict[str, Any]:
    containerized = is_containerized()
    rx_bytes_per_sec, tx_bytes_per_sec = _network_rates()
    memory_total_bytes, memory_used_bytes, memory_scope = _read_memory(
        containerized=containerized
    )
    cpu_capacity = _read_cpu_capacity(containerized=containerized)
    process_memory_bytes = _read_process_memory()
    storage_percent = _storage_percent(DATA_DIR)
    return {
        "runtime_mode": "docker" if containerized else "native",
        "instance_name": platform.node() or "unknown",
        "distribution": _distribution_name(),
        "kernel_version": platform.release() or "unknown",
        "architecture": platform.machine().lower() or "unknown",
        "python_version": platform.python_version() or sys.version.split()[0],
        "cpu_capacity": cpu_capacity,
        "service_started_at": _PROCESS_STARTED_AT,
        "service_uptime_seconds": max(
            0, int(time.monotonic() - _PROCESS_STARTED_MONOTONIC)
        ),
        "process_cpu_percent": _read_process_cpu_percent(cpu_capacity),
        "process_memory_bytes": process_memory_bytes,
        "process_memory_percent": _percentage(
            process_memory_bytes, memory_total_bytes
        ),
        "memory_scope": memory_scope,
        "memory_percent": _percentage(memory_used_bytes, memory_total_bytes),
        "storage_percent": storage_percent,
        "network_rx_bytes_per_sec": _nullable_round(rx_bytes_per_sec),
        "network_tx_bytes_per_sec": _nullable_round(tx_bytes_per_sec),
    }


def snapshot() -> dict[str, Any]:
    """Return one shared runtime sample for all dashboard consumers."""
    global _RUNTIME_SNAPSHOT_CACHE, _RUNTIME_SNAPSHOT_CAPTURED_AT
    with _RUNTIME_SNAPSHOT_LOCK:
        now = time.monotonic()
        if (
            _RUNTIME_SNAPSHOT_CACHE is not None
            and now - _RUNTIME_SNAPSHOT_CAPTURED_AT < _RUNTIME_SNAPSHOT_TTL_SECONDS
        ):
            return dict(_RUNTIME_SNAPSHOT_CACHE)

        captured = _capture_snapshot()
        _RUNTIME_SNAPSHOT_CACHE = dict(captured)
        _RUNTIME_SNAPSHOT_CAPTURED_AT = time.monotonic()
        return captured
