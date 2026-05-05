"""
sysview.actions — all mutating operations on processes.

Every public function that performs a destructive action requires an
explicit `confirmed: bool` parameter.  Callers are responsible for
obtaining that confirmation from the user before setting it to True.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from typing import Optional

import psutil

from config import PROTECTED_NAMES


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ActionResult:
    success: bool
    message: str


# ── Guards ────────────────────────────────────────────────────────────────────

def _guard(pid: int, confirmed: bool) -> Optional[ActionResult]:
    """Return an error ActionResult if the action must be blocked; None if clear."""
    if not confirmed:
        return ActionResult(False, "Action aborted: confirmation not granted.")
    try:
        proc = psutil.Process(pid)
        name = proc.name().lower()
        user = proc.username()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        return ActionResult(False, f"Cannot access process {pid}: {exc}")

    if name in PROTECTED_NAMES or user == "root":
        return ActionResult(False,
            f"Process '{name}' (pid {pid}) is protected and cannot be acted upon.")
    return None


# ── Actions ───────────────────────────────────────────────────────────────────

def kill_process(pid: int, confirmed: bool, force: bool = False) -> ActionResult:
    """
    Terminate a process.  Uses SIGTERM by default; SIGKILL when force=True.
    Always requires confirmed=True.
    """
    if (err := _guard(pid, confirmed)):
        return err
    try:
        proc = psutil.Process(pid)
        sig  = signal.SIGKILL if force else signal.SIGTERM
        proc.send_signal(sig)
        sig_name = "SIGKILL" if force else "SIGTERM"
        return ActionResult(True, f"Sent {sig_name} to '{proc.name()}' (pid {pid}).")
    except psutil.NoSuchProcess:
        return ActionResult(False, f"Process {pid} no longer exists.")
    except psutil.AccessDenied:
        return ActionResult(False,
            f"Permission denied for pid {pid}. Try running sysview with elevated privileges.")
    except Exception as exc:
        return ActionResult(False, f"Unexpected error: {exc}")


def renice_process(pid: int, nice: int, confirmed: bool) -> ActionResult:
    """
    Change the scheduling priority (nice value) of a process.
    nice: -20 (highest priority) to 19 (lowest).
    Lowering priority (higher nice) requires no special privileges.
    """
    if (err := _guard(pid, confirmed)):
        return err
    if not -20 <= nice <= 19:
        return ActionResult(False, "Nice value must be between -20 and 19.")
    try:
        proc = psutil.Process(pid)
        proc.nice(nice)
        return ActionResult(True,
            f"Set nice={nice} for '{proc.name()}' (pid {pid}).")
    except psutil.AccessDenied:
        return ActionResult(False,
            "Raising priority (negative nice) requires root.")
    except psutil.NoSuchProcess:
        return ActionResult(False, f"Process {pid} no longer exists.")


def freeze_process(pid: int, confirmed: bool) -> ActionResult:
    """Suspend a process with SIGSTOP (does not terminate it)."""
    if (err := _guard(pid, confirmed)):
        return err
    try:
        proc = psutil.Process(pid)
        proc.suspend()
        return ActionResult(True,
            f"Suspended (SIGSTOP) '{proc.name()}' (pid {pid}).")
    except psutil.AccessDenied:
        return ActionResult(False, f"Permission denied for pid {pid}.")
    except psutil.NoSuchProcess:
        return ActionResult(False, f"Process {pid} no longer exists.")


def resume_process(pid: int, confirmed: bool) -> ActionResult:
    """Resume a previously suspended process with SIGCONT."""
    if (err := _guard(pid, confirmed)):
        return err
    try:
        proc = psutil.Process(pid)
        proc.resume()
        return ActionResult(True,
            f"Resumed (SIGCONT) '{proc.name()}' (pid {pid}).")
    except psutil.AccessDenied:
        return ActionResult(False, f"Permission denied for pid {pid}.")
    except psutil.NoSuchProcess:
        return ActionResult(False, f"Process {pid} no longer exists.")


def drop_caches(confirmed: bool) -> ActionResult:
    """
    Request the Linux kernel to drop page/slab caches.
    Writes to /proc/sys/vm/drop_caches — requires root.
    Safe: only flushes clean, reclaimable cache (not dirty data).
    No-op on non-Linux platforms (returns informational message).
    """
    if not confirmed:
        return ActionResult(False, "Action aborted: confirmation not granted.")

    import platform
    if platform.system() != "Linux":
        return ActionResult(False,
            "Cache drop is Linux-only (/proc/sys/vm/drop_caches).")

    try:
        # Sync first to flush dirty pages to disk
        os.sync()
        with open("/proc/sys/vm/drop_caches", "w") as fh:
            fh.write("3\n")   # 1=page cache, 2=dentries+inodes, 3=all
        return ActionResult(True,
            "Kernel page/slab caches dropped successfully.")
    except PermissionError:
        return ActionResult(False,
            "Dropping caches requires root. Run sysview with sudo.")
    except FileNotFoundError:
        return ActionResult(False,
            "/proc/sys/vm/drop_caches not found (not Linux?).")
    except Exception as exc:
        return ActionResult(False, f"Unexpected error: {exc}")