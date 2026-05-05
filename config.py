"""
sysview — configuration, thresholds, and constants.
All tuneable values live here; nothing is hardcoded elsewhere.
"""

from __future__ import annotations

# ── Refresh ───────────────────────────────────────────────────────────────────
REFRESH_INTERVAL: float = 1.0          # seconds between metric collection
SPARKLINE_HISTORY: int  = 60           # samples kept for CPU / RAM sparklines

# ── Pressure-score weights (must sum to 1.0) ─────────────────────────────────
SCORE_WEIGHT_CPU: float = 0.40
SCORE_WEIGHT_MEM: float = 0.40
SCORE_WEIGHT_IO:  float = 0.20

# ── Alert thresholds (percentage) ────────────────────────────────────────────
ALERT_CPU_PCT: float = 90.0
ALERT_MEM_PCT: float = 85.0
ALERT_SWAP_PCT: float = 80.0

# ── Auto-free trigger threshold ──────────────────────────────────────────────
AUTOFREE_MEM_THRESHOLD_PCT: float = 90.0

# ── Process priority bonus (lowers kill-score; higher = safer from auto-kill) ─
SYSTEM_PRIORITY_BONUS: float = 50.0
USER_PRIORITY_BONUS:   float = 10.0

# ── Processes immune to automated actions ────────────────────────────────────
PROTECTED_NAMES: frozenset[str] = frozenset({
    "systemd", "init", "kthreadd", "migration",
    "watchdog", "ksoftirqd", "kworker",
    "sshd", "dbus-daemon", "udevd", "journald",
    "kernel", "python3", "sysview",
})

# ── UI ────────────────────────────────────────────────────────────────────────
MAX_VISIBLE_PROCS: int = 40            # rows shown in TUI process table
SORT_DEFAULT: str      = "score"       # cpu | mem | pid | name | score