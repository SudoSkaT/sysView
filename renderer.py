"""
sysview.renderer — curses-based terminal UI.

Layout (top to bottom):
  [header]        hostname, uptime, load average, timestamp
  [cpu bar]       overall + per-core mini-bars + sparkline
  [mem bar]       RAM + Swap bars + sparkline
  [alerts]        inline alert strip (only when active)
  [process table] scrollable, sortable process list
  [footer]        keybinding help
"""

from __future__ import annotations

import curses
import time
from collections import deque
from typing import List, Optional

from collector import Collector, ProcessInfo, SystemSnapshot
from analyzer import Analyzer, AnalysisResult
from actions import (
    kill_process, renice_process,
    freeze_process, resume_process, drop_caches,
)
from config import REFRESH_INTERVAL, SORT_DEFAULT, MAX_VISIBLE_PROCS


# ── Colour pair indices ───────────────────────────────────────────────────────
C_HEADER   = 1
C_BAR_OK   = 2
C_BAR_WARN = 3
C_BAR_CRIT = 4
C_TITLE    = 5
C_SELECTED = 6
C_ALERT    = 7
C_DIM      = 8
C_BOLD_OK  = 9
C_PROTECT  = 10


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_HEADER,   curses.COLOR_CYAN,    -1)
    curses.init_pair(C_BAR_OK,   curses.COLOR_GREEN,   -1)
    curses.init_pair(C_BAR_WARN, curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_BAR_CRIT, curses.COLOR_RED,     -1)
    curses.init_pair(C_TITLE,    curses.COLOR_WHITE,   -1)
    curses.init_pair(C_SELECTED, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_ALERT,    curses.COLOR_BLACK,   curses.COLOR_RED)
    curses.init_pair(C_DIM,      curses.COLOR_WHITE,   -1)
    curses.init_pair(C_BOLD_OK,  curses.COLOR_GREEN,   -1)
    curses.init_pair(C_PROTECT,  curses.COLOR_MAGENTA, -1)


# ── Sparkline ─────────────────────────────────────────────────────────────────
_SPARK = " ▁▂▃▄▅▆▇█"

def _sparkline(values: deque, width: int) -> str:
    if not values:
        return " " * width
    samples = list(values)[-width:]
    result  = []
    for v in samples:
        idx = int(v / 100 * (len(_SPARK) - 1))
        result.append(_SPARK[min(idx, len(_SPARK) - 1)])
    return "".join(result).rjust(width)


# ── Bar rendering ─────────────────────────────────────────────────────────────

def _bar_color(pct: float) -> int:
    if pct >= 85:
        return curses.color_pair(C_BAR_CRIT) | curses.A_BOLD
    if pct >= 60:
        return curses.color_pair(C_BAR_WARN)
    return curses.color_pair(C_BAR_OK)


def _draw_bar(win, row: int, col: int, label: str,
              pct: float, width: int, extra: str = "") -> None:
    filled = int(pct / 100 * width)
    bar    = "█" * filled + "░" * (width - filled)
    attr   = _bar_color(pct)
    try:
        win.addstr(row, col, f"{label:<5}", curses.color_pair(C_TITLE) | curses.A_BOLD)
        win.addstr(row, col + 5, "[", curses.color_pair(C_DIM))
        win.addstr(row, col + 6, bar[:filled], attr)
        win.addstr(row, col + 6 + filled, bar[filled:], curses.color_pair(C_DIM))
        win.addstr(row, col + 6 + width, f"] {pct:5.1f}%  {extra}",
                   curses.color_pair(C_DIM))
    except curses.error:
        pass


# ── Confirmation dialog ───────────────────────────────────────────────────────

def _confirm_dialog(win, prompt: str) -> bool:
    """
    Draw a centred confirmation box and return True only if user presses 'y'.
    Any other key cancels.
    """
    max_y, max_x = win.getmaxyx()
    lines = ["", f"  {prompt}  ", "", "  [y] Confirm    [any key] Cancel  ", ""]
    box_w = max(len(l) for l in lines) + 4
    box_h = len(lines) + 2
    start_y = max((max_y - box_h) // 2, 0)
    start_x = max((max_x - box_w) // 2, 0)

    try:
        popup = curses.newwin(box_h, box_w, start_y, start_x)
        popup.bkgd(" ", curses.color_pair(C_ALERT) | curses.A_BOLD)
        popup.box()
        for i, line in enumerate(lines):
            popup.addstr(i + 1, 2, line.center(box_w - 4))
        popup.refresh()
        ch = popup.getch()
        return ch in (ord("y"), ord("Y"))
    except curses.error:
        return False
    finally:
        try:
            popup.clear()
            popup.refresh()
        except curses.error:
            pass


# ── Input dialog ──────────────────────────────────────────────────────────────

def _input_dialog(win, prompt: str, max_len: int = 6) -> Optional[str]:
    """Single-line input box. Returns stripped string or None on Escape."""
    max_y, max_x = win.getmaxyx()
    box_w = max(len(prompt) + max_len + 6, 40)
    box_h = 5
    start_y = max((max_y - box_h) // 2, 0)
    start_x = max((max_x - box_w) // 2, 0)
    buf = []
    try:
        popup = curses.newwin(box_h, box_w, start_y, start_x)
        curses.echo()
        curses.curs_set(1)
        while True:
            popup.bkgd(" ", curses.color_pair(C_SELECTED))
            popup.box()
            popup.addstr(1, 2, prompt)
            popup.addstr(2, 2, "".join(buf) + " " * (max_len - len(buf)))
            popup.addstr(3, 2, "Enter=confirm  Esc=cancel")
            popup.move(2, 2 + len(buf))
            popup.refresh()
            ch = popup.getch()
            if ch == 27:           # Escape
                return None
            if ch in (10, 13):     # Enter
                return "".join(buf).strip() or None
            if ch in (127, curses.KEY_BACKSPACE):
                buf = buf[:-1]
            elif len(buf) < max_len and 32 <= ch <= 126:
                buf.append(chr(ch))
    except curses.error:
        return None
    finally:
        curses.noecho()
        curses.curs_set(0)
        try:
            popup.clear()
            popup.refresh()
        except curses.error:
            pass


# ── Status bar ────────────────────────────────────────────────────────────────

def _draw_status(win, row: int, msg: str, error: bool = False) -> None:
    max_y, max_x = win.getmaxyx()
    attr = (curses.color_pair(C_BAR_CRIT) | curses.A_BOLD
            if error else curses.color_pair(C_BOLD_OK) | curses.A_BOLD)
    try:
        win.addstr(row, 0, msg[:max_x - 1].ljust(max_x - 1), attr)
    except curses.error:
        pass


# ── Main renderer ─────────────────────────────────────────────────────────────

class Renderer:

    SORT_KEYS = ["score", "cpu", "mem", "pid", "name"]

    def __init__(self, collector: Collector, analyzer: Analyzer) -> None:
        self._collector  = collector
        self._analyzer   = analyzer
        self._sort_by    = SORT_DEFAULT
        self._scroll     = 0
        self._cursor     = 0
        self._last_snap: Optional[SystemSnapshot]  = None
        self._last_analysis: Optional[AnalysisResult] = None
        self._status_msg: str = ""
        self._status_err: bool = False
        self._status_ts:  float = 0.0

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self, stdscr) -> None:
        _init_colors()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(int(REFRESH_INTERVAL * 1000))

        last_collect = 0.0

        while True:
            now = time.monotonic()
            if now - last_collect >= REFRESH_INTERVAL:
                snap     = self._collector.snapshot()
                analysis = self._analyzer.analyse(snap)
                self._last_snap     = snap
                self._last_analysis = analysis
                last_collect = now

            if self._last_snap:
                self._draw(stdscr, self._last_snap, self._last_analysis)

            ch = stdscr.getch()
            if ch != -1:
                quit_flag = self._handle_key(ch, stdscr)
                if quit_flag:
                    break

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, win, snap: SystemSnapshot,
              analysis: AnalysisResult) -> None:
        win.erase()
        max_y, max_x = win.getmaxyx()
        row = 0

        row = self._draw_header(win, snap, row, max_x)
        row = self._draw_cpu_section(win, snap, row, max_x)
        row = self._draw_mem_section(win, snap, row, max_x)
        row = self._draw_alerts(win, analysis, row, max_x)
        row = self._draw_table(win, snap, analysis, row, max_y, max_x)
        self._draw_footer(win, max_y, max_x)

        if self._status_msg and time.monotonic() - self._status_ts < 3.0:
            _draw_status(win, max_y - 2, self._status_msg, self._status_err)

        win.refresh()

    def _draw_header(self, win, snap: SystemSnapshot,
                     row: int, max_x: int) -> int:
        import socket
        host    = socket.gethostname()
        uptime  = snap.uptime_s
        h, rem  = divmod(int(uptime), 3600)
        m, s    = divmod(rem, 60)
        load    = snap.load_avg
        ts      = time.strftime("%H:%M:%S", time.localtime(snap.timestamp))
        procs_n = len(snap.processes)

        header = (f" sysview  {host}  up {h:02d}:{m:02d}:{s:02d}"
                  f"  load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}"
                  f"  tasks: {procs_n}  {ts} ")
        try:
            win.addstr(row, 0,
                       header[:max_x - 1].ljust(max_x - 1),
                       curses.color_pair(C_HEADER) | curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass
        return row + 1

    def _draw_cpu_section(self, win, snap: SystemSnapshot,
                          row: int, max_x: int) -> int:
        bar_w = min(40, max_x - 30)
        spark = _sparkline(self._collector.history.cpu, 20)
        extra = f"▸ {spark}"
        _draw_bar(win, row, 0, "CPU", snap.cpu_pct, bar_w, extra)
        row += 1

        # Per-core mini bars (single row, compact)
        cores_str = ""
        for i, c in enumerate(snap.cpu_per_core[:16]):
            block = "█" if c >= 85 else ("▓" if c >= 60 else ("▒" if c >= 30 else "░"))
            cores_str += f" C{i}:{block}"
        try:
            win.addstr(row, 0, ("     " + cores_str)[:max_x - 1],
                       curses.color_pair(C_DIM))
        except curses.error:
            pass
        return row + 1

    def _draw_mem_section(self, win, snap: SystemSnapshot,
                          row: int, max_x: int) -> int:
        bar_w    = min(40, max_x - 30)
        spark_m  = _sparkline(self._collector.history.mem, 20)
        mem_extra = (f"{snap.mem_used_mb:.0f}/{snap.mem_total_mb:.0f} MB"
                     f"  ▸ {spark_m}")
        _draw_bar(win, row, 0, "RAM", snap.mem_pct, bar_w, mem_extra)
        row += 1

        if snap.swap_total_mb > 0:
            spark_s   = _sparkline(self._collector.history.swap, 20)
            sw_extra  = (f"{snap.swap_used_mb:.0f}/{snap.swap_total_mb:.0f} MB"
                         f"  ▸ {spark_s}")
            _draw_bar(win, row, 0, "SWAP", snap.swap_pct, bar_w, sw_extra)
            row += 1

        return row

    def _draw_alerts(self, win, analysis: AnalysisResult,
                     row: int, max_x: int) -> int:
        if not analysis.alerts:
            return row
        msg = "  ".join(a.message for a in analysis.alerts)
        attr = curses.color_pair(C_ALERT) | curses.A_BOLD
        try:
            win.addstr(row, 0,
                       f" ALERT  {msg} "[:max_x - 1].ljust(max_x - 1),
                       attr)
        except curses.error:
            pass
        return row + 1

    def _sorted_procs(self, procs: list[ProcessInfo]) -> list[ProcessInfo]:
        key_map = {
            "cpu":   lambda p: p.cpu_pct,
            "mem":   lambda p: p.mem_pct,
            "pid":   lambda p: p.pid,
            "name":  lambda p: p.name.lower(),
            "score": lambda p: p.score,
        }
        reverse = self._sort_by != "name"
        return sorted(procs, key=key_map.get(self._sort_by, lambda p: p.score),
                      reverse=reverse)

    def _draw_table(self, win, snap: SystemSnapshot,
                    analysis: AnalysisResult,
                    row: int, max_y: int, max_x: int) -> int:
        # Table header
        col_fmt = f" {'PID':>7}  {'NAME':<18}  {'USER':<10}  {'CPU%':>6}  {'MEM%':>6}  {'RSS MB':>7}  {'NICE':>4}  {'STATUS':<8}  {'SCORE':>6}"
        try:
            win.addstr(row, 0,
                       col_fmt[:max_x - 1].ljust(max_x - 1),
                       curses.color_pair(C_TITLE) | curses.A_BOLD | curses.A_UNDERLINE)
        except curses.error:
            pass
        row += 1

        table_rows = max_y - row - 2   # reserve 2 lines for footer
        procs = self._sorted_procs(snap.processes)
        total = len(procs)

        # Clamp scroll and cursor
        self._cursor = max(0, min(self._cursor, total - 1))
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        if self._cursor >= self._scroll + table_rows:
            self._scroll = self._cursor - table_rows + 1

        candidate_pids = {p.pid for p in analysis.kill_candidates}

        for i, p in enumerate(procs[self._scroll: self._scroll + table_rows]):
            abs_idx = self._scroll + i
            is_selected = abs_idx == self._cursor

            line = (f" {p.pid:>7}  {p.name[:18]:<18}  {p.username[:10]:<10}"
                    f"  {p.cpu_pct:>6.1f}  {p.mem_pct:>6.1f}  {p.mem_rss_mb:>7.1f}"
                    f"  {p.nice:>4}  {p.status[:8]:<8}  {p.score:>6.1f}")

            if is_selected:
                attr = curses.color_pair(C_SELECTED) | curses.A_BOLD
            elif p.protected:
                attr = curses.color_pair(C_PROTECT)
            elif p.pid in candidate_pids:
                attr = curses.color_pair(C_BAR_WARN) | curses.A_BOLD
            elif p.cpu_pct > 50 or p.mem_pct > 50:
                attr = curses.color_pair(C_BAR_CRIT)
            else:
                attr = curses.color_pair(C_DIM)

            try:
                win.addstr(row, 0, line[:max_x - 1].ljust(max_x - 1), attr)
            except curses.error:
                pass
            row += 1

        return row

    def _draw_footer(self, win, max_y: int, max_x: int) -> None:
        keys = (" q:Quit  k:Kill  K:ForceKill  f:Freeze  r:Resume"
                "  n:Renice  d:DropCache  s:Sort  ↑↓:Navigate ")
        try:
            win.addstr(max_y - 1, 0,
                       keys[:max_x - 1].ljust(max_x - 1),
                       curses.color_pair(C_TITLE) | curses.A_REVERSE)
        except curses.error:
            pass

    # ── Key handling ─────────────────────────────────────────────────────────

    def _set_status(self, msg: str, error: bool = False) -> None:
        self._status_msg = msg
        self._status_err = error
        self._status_ts  = time.monotonic()

    def _selected_proc(self) -> Optional[ProcessInfo]:
        if not self._last_snap:
            return None
        procs = self._sorted_procs(self._last_snap.processes)
        if 0 <= self._cursor < len(procs):
            return procs[self._cursor]
        return None

    def _handle_key(self, ch: int, win) -> bool:
        # Navigation
        if ch in (curses.KEY_UP, ord("k") if False else curses.KEY_UP):
            pass
        if ch == curses.KEY_UP:
            self._cursor = max(0, self._cursor - 1)
        elif ch == curses.KEY_DOWN:
            n = len(self._last_snap.processes) if self._last_snap else 0
            self._cursor = min(n - 1, self._cursor + 1)
        elif ch == curses.KEY_PPAGE:
            self._cursor = max(0, self._cursor - 10)
        elif ch == curses.KEY_NPAGE:
            n = len(self._last_snap.processes) if self._last_snap else 0
            self._cursor = min(n - 1, self._cursor + 10)

        # Quit
        elif ch in (ord("q"), ord("Q")):
            return True

        # Sort cycle
        elif ch in (ord("s"), ord("S")):
            idx = self.SORT_KEYS.index(self._sort_by)
            self._sort_by = self.SORT_KEYS[(idx + 1) % len(self.SORT_KEYS)]
            self._set_status(f"Sort: {self._sort_by}")

        # Kill (SIGTERM)
        elif ch == ord("k"):
            proc = self._selected_proc()
            if proc:
                if _confirm_dialog(win,
                        f"Kill '{proc.name}' (pid {proc.pid}) with SIGTERM?"):
                    res = kill_process(proc.pid, confirmed=True, force=False)
                    self._set_status(res.message, not res.success)

        # Force kill (SIGKILL)
        elif ch == ord("K"):
            proc = self._selected_proc()
            if proc:
                if _confirm_dialog(win,
                        f"FORCE KILL '{proc.name}' (pid {proc.pid}) with SIGKILL?"):
                    res = kill_process(proc.pid, confirmed=True, force=True)
                    self._set_status(res.message, not res.success)

        # Freeze
        elif ch == ord("f"):
            proc = self._selected_proc()
            if proc:
                if _confirm_dialog(win,
                        f"Freeze (SIGSTOP) '{proc.name}' (pid {proc.pid})?"):
                    res = freeze_process(proc.pid, confirmed=True)
                    self._set_status(res.message, not res.success)

        # Resume
        elif ch == ord("r"):
            proc = self._selected_proc()
            if proc:
                if _confirm_dialog(win,
                        f"Resume (SIGCONT) '{proc.name}' (pid {proc.pid})?"):
                    res = resume_process(proc.pid, confirmed=True)
                    self._set_status(res.message, not res.success)

        # Renice
        elif ch == ord("n"):
            proc = self._selected_proc()
            if proc:
                val = _input_dialog(win,
                    f"New nice value for '{proc.name}' (-20..19): ")
                if val is not None:
                    try:
                        nice_val = int(val)
                        if _confirm_dialog(win,
                                f"Set nice={nice_val} for '{proc.name}' (pid {proc.pid})?"):
                            res = renice_process(proc.pid, nice_val, confirmed=True)
                            self._set_status(res.message, not res.success)
                    except ValueError:
                        self._set_status("Invalid nice value.", error=True)

        # Drop caches
        elif ch == ord("d"):
            if _confirm_dialog(win,
                    "Drop kernel page/slab caches? (requires root)"):
                res = drop_caches(confirmed=True)
                self._set_status(res.message, not res.success)

        return False