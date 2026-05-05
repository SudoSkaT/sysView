"""
sysview.collector — low-level metric collection.

Wraps psutil into typed dataclasses so the rest of the application
never imports psutil directly; swapping the backend stays trivial.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

import psutil

from config import (
    SPARKLINE_HISTORY,
    SCORE_WEIGHT_CPU,
    SCORE_WEIGHT_MEM,
    SCORE_WEIGHT_IO,
    SYSTEM_PRIORITY_BONUS,
    USER_PRIORITY_BONUS,
    PROTECTED_NAMES,
)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ProcessInfo:
    pid:        int
    name:       str
    username:   str
    status:     str
    cpu_pct:    float
    mem_pct:    float
    mem_rss_mb: float
    io_read_mb: float
    io_write_mb: float
    nice:       int
    score:      float = 0.0
    protected:  bool  = False


@dataclass
class SystemSnapshot:
    timestamp:    float
    cpu_pct:      float
    cpu_per_core: List[float]
    mem_total_mb: float
    mem_used_mb:  float
    mem_pct:      float
    swap_total_mb: float
    swap_used_mb: float
    swap_pct:     float
    load_avg:     tuple          # (1m, 5m, 15m) — Linux/macOS only
    uptime_s:     float
    processes:    List[ProcessInfo]


@dataclass
class MetricHistory:
    cpu:  Deque[float] = field(default_factory=lambda: deque(maxlen=SPARKLINE_HISTORY))
    mem:  Deque[float] = field(default_factory=lambda: deque(maxlen=SPARKLINE_HISTORY))
    swap: Deque[float] = field(default_factory=lambda: deque(maxlen=SPARKLINE_HISTORY))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _io_counters(proc: psutil.Process) -> tuple[float, float]:
    """
    Return (read_mb, write_mb) or (0, 0) if unavailable / not permitted.
    Handles non-standard /proc layouts (containers, WSL) that may raise
    ValueError when expected fields are missing.
    """
    try:
        io = proc.io_counters()
        return io.read_bytes / 1_048_576, io.write_bytes / 1_048_576
    except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError, ValueError):
        return 0.0, 0.0


def _pressure_score(p: ProcessInfo) -> float:
    """
    Composite pressure score in [0, 100].
    Processes with high CPU *and* high memory pressure score highest.
    Protected / system processes receive a large negative bonus.
    """
    raw = (
        p.cpu_pct    * SCORE_WEIGHT_CPU
        + p.mem_pct  * SCORE_WEIGHT_MEM
        + min(p.io_read_mb + p.io_write_mb, 100) * SCORE_WEIGHT_IO
    )
    if p.protected:
        raw -= SYSTEM_PRIORITY_BONUS
    elif p.username != "root":
        raw -= USER_PRIORITY_BONUS
    return max(0.0, min(raw, 100.0))


def _is_protected(name: str, username: str) -> bool:
    return name.lower() in PROTECTED_NAMES or username == "root"


# ── Public collector ──────────────────────────────────────────────────────────

class Collector:
    """
    Stateful metric collector.  Call `snapshot()` periodically; it returns
    a fresh `SystemSnapshot` and appends to internal `history`.
    """

    def __init__(self) -> None:
        self.history: MetricHistory = MetricHistory()
        self._boot_time: float = psutil.boot_time()
        # Warm up CPU percent (first call always returns 0.0 per psutil docs)
        psutil.cpu_percent(interval=None)
        for p in psutil.process_iter():
            try:
                p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    # ── System-level ──────────────────────────────────────────────────────────

    def _cpu(self) -> tuple[float, list[float]]:
        overall = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        return overall, per_core

    def _memory(self) -> tuple[float, float, float]:
        vm = psutil.virtual_memory()
        return vm.total / 1_048_576, vm.used / 1_048_576, vm.percent

    def _swap(self) -> tuple[float, float, float]:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sw = psutil.swap_memory()
        return sw.total / 1_048_576, sw.used / 1_048_576, sw.percent

    def _load(self) -> tuple:
        try:
            return os.getloadavg()
        except (AttributeError, OSError):
            return (0.0, 0.0, 0.0)

    # ── Process list ──────────────────────────────────────────────────────────

    def _processes(self) -> list[ProcessInfo]:
        procs: list[ProcessInfo] = []
        attrs = ["pid", "name", "username", "status",
                 "cpu_percent", "memory_percent", "memory_info",
                 "nice"]
        for proc in psutil.process_iter(attrs, ad_value=None):
            try:
                i = proc.info
                if i["pid"] is None:
                    continue
                name = i["name"] or "?"
                user = i["username"] or "?"
                rss  = (i["memory_info"].rss / 1_048_576
                        if i["memory_info"] else 0.0)
                r_mb, w_mb = _io_counters(proc)
                protected  = _is_protected(name, user)
                p = ProcessInfo(
                    pid         = i["pid"],
                    name        = name,
                    username    = user,
                    status      = i["status"] or "?",
                    cpu_pct     = i["cpu_percent"] or 0.0,
                    mem_pct     = i["memory_percent"] or 0.0,
                    mem_rss_mb  = rss,
                    io_read_mb  = r_mb,
                    io_write_mb = w_mb,
                    nice        = i["nice"] or 0,
                    protected   = protected,
                )
                p.score = _pressure_score(p)
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return procs

    # ── Public API ────────────────────────────────────────────────────────────

    def snapshot(self) -> SystemSnapshot:
        cpu_pct, cpu_cores      = self._cpu()
        mem_total, mem_used, mem_pct = self._memory()
        sw_total, sw_used, sw_pct   = self._swap()

        self.history.cpu.append(cpu_pct)
        self.history.mem.append(mem_pct)
        self.history.swap.append(sw_pct)

        return SystemSnapshot(
            timestamp     = time.time(),
            cpu_pct       = cpu_pct,
            cpu_per_core  = cpu_cores,
            mem_total_mb  = mem_total,
            mem_used_mb   = mem_used,
            mem_pct       = mem_pct,
            swap_total_mb = sw_total,
            swap_used_mb  = sw_used,
            swap_pct      = sw_pct,
            load_avg      = self._load(),
            uptime_s      = time.time() - self._boot_time,
            processes     = self._processes(),
        )