# sysView 

**System monitor and process manager for resource-constrained machines.**

A lightweight, interactive tool to monitor CPU, memory, and swap usage in real-time, identify resource-hogging processes, and manage system pressure with confidence.

---

##  Table of Contents

- [Why sysView?](#why-sysview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Modes](#usage-modes)
- [Configuration](#configuration)
- [Safety & Protections](#safety--protections)
- [Roadmap](#roadmap)
- [Contact](#contact)

---

##  Why sysView?

Running out of memory? Swap thrashing? A single runaway process eating all your resources?

**sysView** is built for systems that can't afford to wait for a GUI, can't run heavyweight monitoring tools, and need *smart* intervention. Perfect for:
-  **Embedded systems** and single-board computers (RPi, Jetson, etc.)
-  **Headless servers** and VPS with tight resource budgets
-  **Old laptops** and underpowered machines
-  **Container environments** where every MB counts

It combines **real-time monitoring**, **automatic alerting**, and **safe process management** — all from the terminal.

---

##  Features

- **Interactive TUI Dashboard**
  - Real-time CPU, memory, swap, and load average metrics
  - Sortable process table with pressure scoring (CPU + Memory + I/O)
  - Sparkline graphs for trending
  - Color-coded alerts (🔴 critical, 🟠 warning, 🟢 normal)
  - Keyboard-driven: sort, kill, suspend, renice processes without leaving the terminal

- **Headless CLI Modes**
  - One-shot snapshots (`--cli`)
  - Continuous polling (`--watch SECONDS`)
  - JSON export for scripting and integration

- **Memory Relief Mode** (`--free`)
  - Interactively identify processes causing memory pressure
  - Kill or renice them with confirmation
  - Dry-run mode to preview actions

- **Automated Actions**
  - Auto-kill processes exceeding a RAM threshold (`--kill-above PCT`)
  - Protected system processes (never auto-killed)
  - No mutations without explicit confirmation

- **Smart Pressure Scoring**
  - Composite score: 40% CPU + 40% Memory + 20% I/O
  - Rank processes by actual system impact, not just RAM usage
  - Prioritize protecting system services (systemd, sshd, dbus, etc.)

---

## Requirements

- **Python 3.10+**
- **psutil 7.2.2+** (installed automatically)
- Linux, macOS, or WSL
- Terminal with 256-color support (for TUI)

---

  Installation

```bash
git clone https://github.com/SudoSkaT/sysView.git
cd sysView
bash install.sh
```

This installs sysView to `/usr/local/bin/sysview` (or `~/.local/bin/sysview` for non-root).

**Verify installation:**
```bash
sysview --help
```

---

## Quick Start

### Interactive Dashboard (Default)
```bash
sysview
```
Opens a real-time TUI with live metrics and an interactive process table.

**Keyboard shortcuts:**
- `q` or `Ctrl+C` — Exit
- `↑/↓` — Scroll process table
- `c`, `m`, `p`, `s` — Sort by CPU, Memory, PID, Pressure Score
- `k` — Kill selected process (with confirmation)
- `r` — Renice selected process (adjust priority)
- `z` — Suspend process (SIGSTOP)
- `u` — Unsuspend process (SIGCONT)
- `f` — Free page cache
- `h` — Help

### One-Shot Snapshot
```bash
sysview --cli
```
Prints current system metrics and top processes, then exits.

### Continuous Monitoring (Headless)
```bash
sysview --watch 2
```
Refresh metrics every 2 seconds (text output, no TUI).

### JSON Export (for scripting)
```bash
sysview --cli --export json
```
Outputs machine-readable snapshot; great for monitoring dashboards or automation.

### Memory Relief Mode
```bash
sysview --free
```
Interactively rank processes by memory pressure and kill/suspend them.

```bash
sysview --free --dry-run
```
Preview what would be killed without actually doing it.

### Auto-Kill Threshold
```bash
sysview --kill-above 80
```
Kill all processes consuming >80% RAM (with confirmation). Skips protected processes.

---

##  Configuration

All tuneable values are in [config.py](config.py):

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `REFRESH_INTERVAL` | 1.0 s | How often metrics are collected |
| `ALERT_CPU_PCT` | 90% | CPU threshold for alerts |
| `ALERT_MEM_PCT` | 85% | Memory threshold for alerts |
| `ALERT_SWAP_PCT` | 80% | Swap threshold for alerts |
| `AUTOFREE_MEM_THRESHOLD_PCT` | 90% | Trigger memory-relief automatically |
| `SCORE_WEIGHT_CPU` | 0.40 | Pressure score: CPU weight |
| `SCORE_WEIGHT_MEM` | 0.40 | Pressure score: Memory weight |
| `SCORE_WEIGHT_IO` | 0.20 | Pressure score: I/O weight |
| `PROTECTED_NAMES` | `{systemd, sshd, init, kernel, ...}` | Processes immune to auto-kill |

Edit [config.py](config.py) to customize for your environment.

---

##  Safety & Protections

sysView is designed to be **safe by default**:

 **Protected Processes** — System services (systemd, sshd, dbus, journald, etc.) are never auto-killed.

 **Explicit Confirmation** — All destructive actions require user confirmation.

 **Permission Checks** — Killing/suspending processes validates capabilities before attempting.

 **Dry-Run Mode** — Preview actions with `--free --dry-run` before committing.

 **No Surprise Kills** — Even `--kill-above` shows a summary and waits for confirmation.

---

##  Roadmap

This project is **open to community ideas!** We welcome:

-  **Feature suggestions** — New monitoring metrics, alerts, or actions?
-  **Bug reports** — Found an issue? Let us know.
-  **Platform support** — Test on different systems and share feedback.
-  **Documentation improvements** — Better examples, guides, or translations.

**Planned improvements:**
- Historical data logging and trends
- Remote monitoring API
- Configuration profiles (presets for different workloads)
- Custom alert actions (webhooks, email notifications)
- Multi-system dashboard

**Have an idea?** Open an issue or reach out!

---

## Contact

Author:** ING-SkaT

**Email:** casasbrayan404@gmail.com

**Instagram:** ig_skat.twisy

---

Made with ❤️ for low-resource systems.
# sysView
