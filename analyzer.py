"""
sysview.analyzer — pressure analysis and kill-candidate ranking.

The analyzer never *performs* any action; it only returns recommendations
so that actions.py (and the user) retain full control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from collector import ProcessInfo, SystemSnapshot
from config import (
    ALERT_CPU_PCT,
    ALERT_MEM_PCT,
    ALERT_SWAP_PCT,
    AUTOFREE_MEM_THRESHOLD_PCT,
    PROTECTED_NAMES,
)


# ── Alert model ───────────────────────────────────────────────────────────────

@dataclass
class Alert:
    level:   str    # "warn" | "critical"
    metric:  str    # "cpu" | "mem" | "swap"
    value:   float
    message: str


# ── Analysis result ───────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    alerts:            List[Alert]
    kill_candidates:   List[ProcessInfo]   # sorted descending by score
    autofree_advised:  bool
    pressure_summary:  str                 # human-readable one-liner


# ── Analyser ──────────────────────────────────────────────────────────────────

class Analyzer:

    def analyse(self, snap: SystemSnapshot) -> AnalysisResult:
        alerts           = self._build_alerts(snap)
        kill_candidates  = self._rank_candidates(snap.processes)
        autofree_advised = snap.mem_pct >= AUTOFREE_MEM_THRESHOLD_PCT
        pressure_summary = self._summarise(snap, alerts)
        return AnalysisResult(
            alerts           = alerts,
            kill_candidates  = kill_candidates,
            autofree_advised = autofree_advised,
            pressure_summary = pressure_summary,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_alerts(snap: SystemSnapshot) -> list[Alert]:
        alerts: list[Alert] = []

        if snap.cpu_pct >= ALERT_CPU_PCT:
            level = "critical" if snap.cpu_pct >= 98.0 else "warn"
            alerts.append(Alert(level, "cpu", snap.cpu_pct,
                                f"CPU at {snap.cpu_pct:.1f}%"))

        if snap.mem_pct >= ALERT_MEM_PCT:
            level = "critical" if snap.mem_pct >= 95.0 else "warn"
            alerts.append(Alert(level, "mem", snap.mem_pct,
                                f"RAM at {snap.mem_pct:.1f}%"
                                f" ({snap.mem_used_mb:.0f} / {snap.mem_total_mb:.0f} MB)"))

        if snap.swap_pct >= ALERT_SWAP_PCT and snap.swap_total_mb > 0:
            level = "critical" if snap.swap_pct >= 95.0 else "warn"
            alerts.append(Alert(level, "swap", snap.swap_pct,
                                f"Swap at {snap.swap_pct:.1f}%"))

        return alerts

    @staticmethod
    def _rank_candidates(procs: list[ProcessInfo]) -> list[ProcessInfo]:
        """
        Return non-protected processes sorted by pressure score (highest first).
        Only include processes actually consuming resources.
        """
        candidates = [
            p for p in procs
            if not p.protected and (p.cpu_pct > 0.5 or p.mem_pct > 0.5)
        ]
        candidates.sort(key=lambda p: p.score, reverse=True)
        return candidates[:10]

    @staticmethod
    def _summarise(snap: SystemSnapshot, alerts: list[Alert]) -> str:
        if not alerts:
            load = snap.load_avg[0]
            cores = len(snap.cpu_per_core) or 1
            state = "nominal" if load < cores * 0.7 else "moderate"
            return f"System {state} — load {load:.2f}, RAM {snap.mem_pct:.0f}%"

        worst = max(alerts, key=lambda a: a.value)
        return f"ALERT [{worst.level.upper()}]: {worst.message}"