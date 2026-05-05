"""
sysview.cli — headless / scriptable command-line interface.

All output goes to stdout; exit codes follow Unix convention
(0 = success, 1 = general error, 2 = misuse).
"""

from __future__ import annotations

import json
import sys
import time
from typing import Optional

from collector import Collector, SystemSnapshot
from analyzer import Analyzer
from actions import kill_process, drop_caches
from config import ALERT_CPU_PCT, ALERT_MEM_PCT


# ── Formatting helpers ────────────────────────────────────────────────────────

def _mb(value: float) -> str:
    return f"{value:.1f} MB"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _uptime(seconds: float) -> str:
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_text(snap: SystemSnapshot, analysis) -> str:
    lines = []
    lines.append(f"sysview snapshot  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"uptime: {_uptime(snap.uptime_s)}"
                 f"  load: {snap.load_avg[0]:.2f} {snap.load_avg[1]:.2f} {snap.load_avg[2]:.2f}")
    lines.append("")
    lines.append(f"CPU   {_pct(snap.cpu_pct):>8}")
    lines.append(f"RAM   {_pct(snap.mem_pct):>8}  {_mb(snap.mem_used_mb)} / {_mb(snap.mem_total_mb)}")
    if snap.swap_total_mb > 0:
        lines.append(f"SWAP  {_pct(snap.swap_pct):>8}  {_mb(snap.swap_used_mb)} / {_mb(snap.swap_total_mb)}")
    lines.append("")

    if analysis.alerts:
        lines.append("--- ALERTS ---")
        for a in analysis.alerts:
            lines.append(f"  [{a.level.upper()}] {a.message}")
        lines.append("")

    lines.append(f"{'PID':>7}  {'NAME':<18}  {'CPU%':>6}  {'MEM%':>6}  {'RSS MB':>8}  {'SCORE':>6}")
    lines.append("-" * 62)
    for p in snap.processes[:30]:
        lines.append(
            f"{p.pid:>7}  {p.name[:18]:<18}  {p.cpu_pct:>6.1f}  "
            f"{p.mem_pct:>6.1f}  {p.mem_rss_mb:>8.1f}  {p.score:>6.1f}"
        )

    return "\n".join(lines)


def render_json(snap: SystemSnapshot, analysis) -> str:
    data = {
        "timestamp": snap.timestamp,
        "uptime_s":  snap.uptime_s,
        "load_avg":  list(snap.load_avg),
        "cpu": {
            "pct":      snap.cpu_pct,
            "per_core": snap.cpu_per_core,
        },
        "memory": {
            "total_mb": snap.mem_total_mb,
            "used_mb":  snap.mem_used_mb,
            "pct":      snap.mem_pct,
        },
        "swap": {
            "total_mb": snap.swap_total_mb,
            "used_mb":  snap.swap_used_mb,
            "pct":      snap.swap_pct,
        },
        "alerts": [
            {"level": a.level, "metric": a.metric, "message": a.message}
            for a in analysis.alerts
        ],
        "kill_candidates": [
            {"pid": p.pid, "name": p.name, "score": p.score,
             "cpu_pct": p.cpu_pct, "mem_pct": p.mem_pct}
            for p in analysis.kill_candidates
        ],
        "processes": [
            {
                "pid":        p.pid,
                "name":       p.name,
                "username":   p.username,
                "status":     p.status,
                "cpu_pct":    p.cpu_pct,
                "mem_pct":    p.mem_pct,
                "mem_rss_mb": p.mem_rss_mb,
                "nice":       p.nice,
                "score":      p.score,
                "protected":  p.protected,
            }
            for p in snap.processes
        ],
    }
    return json.dumps(data, indent=2)


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_snapshot(fmt: str) -> None:
    collector = Collector()
    analyzer  = Analyzer()
    time.sleep(0.5)           # allow CPU % to warm up
    snap     = collector.snapshot()
    analysis = analyzer.analyse(snap)
    if fmt == "json":
        print(render_json(snap, analysis))
    else:
        print(render_text(snap, analysis))


def cmd_watch(interval: float, fmt: str) -> None:
    collector = Collector()
    analyzer  = Analyzer()
    try:
        while True:
            time.sleep(interval)
            snap     = collector.snapshot()
            analysis = analyzer.analyse(snap)
            if fmt == "text":
                print("\033[2J\033[H", end="")   # clear terminal
            if fmt == "json":
                print(render_json(snap, analysis))
            else:
                print(render_text(snap, analysis))
    except KeyboardInterrupt:
        pass


def cmd_free(dry_run: bool) -> None:
    """
    Interactive free-memory sequence:
      1. Show current pressure.
      2. Prompt for confirmation.
      3. Kill top-pressure candidates one by one (with per-process confirm).
      4. Attempt cache drop.
    """
    collector = Collector()
    analyzer  = Analyzer()
    time.sleep(0.5)
    snap     = collector.snapshot()
    analysis = analyzer.analyse(snap)

    print(f"RAM: {snap.mem_pct:.1f}%  ({snap.mem_used_mb:.0f} / {snap.mem_total_mb:.0f} MB)")

    if not analysis.kill_candidates:
        print("No high-pressure unprotected processes found.")
    else:
        print(f"\nTop pressure candidates:")
        for i, p in enumerate(analysis.kill_candidates[:5], 1):
            print(f"  {i}. [{p.score:5.1f}] pid {p.pid:>6}  {p.name:<20}"
                  f"  cpu {p.cpu_pct:5.1f}%  mem {p.mem_pct:5.1f}%")

    if dry_run:
        print("\n[dry-run] No actions taken.")
        return

    print()
    answer = input("Proceed with killing top candidate? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    for p in analysis.kill_candidates[:3]:
        ans = input(f"  Kill '{p.name}' (pid {p.pid}, score {p.score:.1f})? [y/N] ").strip().lower()
        if ans == "y":
            res = kill_process(p.pid, confirmed=True, force=False)
            print(f"  -> {res.message}")

    ans2 = input("\nAttempt kernel cache drop (requires root)? [y/N] ").strip().lower()
    if ans2 == "y":
        res = drop_caches(confirmed=True)
        print(f"  -> {res.message}")


def cmd_kill_above(threshold: float) -> None:
    """Kill all unprotected processes with RAM usage above threshold%."""
    collector = Collector()
    analyzer  = Analyzer()
    time.sleep(0.5)
    snap     = collector.snapshot()
    analysis = analyzer.analyse(snap)

    targets = [p for p in snap.processes
               if not p.protected and p.mem_pct >= threshold]

    if not targets:
        print(f"No unprotected processes found with RAM >= {threshold}%.")
        return

    targets.sort(key=lambda p: p.mem_pct, reverse=True)
    print(f"Processes with RAM >= {threshold}%:\n")
    for p in targets:
        print(f"  pid {p.pid:>6}  {p.name:<20}  {p.mem_pct:.1f}%  {p.mem_rss_mb:.0f} MB")

    print()
    answer = input("Kill ALL listed processes? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    for p in targets:
        res = kill_process(p.pid, confirmed=True, force=False)
        print(f"  {p.name} (pid {p.pid}): {res.message}")