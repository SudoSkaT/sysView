#!/usr/bin/env python3
"""
sysview — system monitor and process manager for resource-constrained machines.

Usage examples:
  sysview                          Interactive TUI
  sysview --cli                    One-shot text snapshot
  sysview --export json            One-shot JSON snapshot
  sysview --watch 2                Refresh every 2 seconds (text)
  sysview --watch 5 --export json  Refresh every 5 s (JSON)
  sysview --free                   Interactive memory-relief mode
  sysview --free --dry-run         Preview without acting
  sysview --kill-above 80          Kill all processes consuming >80% RAM
"""

from __future__ import annotations

import argparse
import curses
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sysview",
        description="System monitor and process manager for low-resource machines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cli",
        action="store_true",
        help="Print a one-shot text snapshot and exit.",
    )
    mode.add_argument(
        "--watch",
        metavar="SECONDS",
        type=float,
        help="Continuously refresh metrics (headless, text output).",
    )
    mode.add_argument(
        "--free",
        action="store_true",
        help="Interactive memory-relief: identify and kill high-pressure processes.",
    )
    mode.add_argument(
        "--kill-above",
        metavar="PCT",
        type=float,
        dest="kill_above",
        help="Kill all unprotected processes consuming more than PCT%% RAM.",
    )

    parser.add_argument(
        "--export",
        choices=["text", "json"],
        default="text",
        help="Output format for --cli and --watch modes (default: text).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without performing any action (--free only).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    # --export without an explicit mode flag implies a one-shot CLI snapshot
    if args.export != "text" and not any([
            args.cli, args.watch is not None, args.free, args.kill_above]):
        args.cli = True

    # Lazy imports keep startup fast for non-TUI paths
    if args.cli:
        from cli import cmd_snapshot
        cmd_snapshot(args.export)

    elif args.watch is not None:
        from cli import cmd_watch
        cmd_watch(args.watch, args.export)

    elif args.free:
        from cli import cmd_free
        cmd_free(dry_run=args.dry_run)

    elif args.kill_above is not None:
        if not 0 < args.kill_above <= 100:
            print("Error: --kill-above value must be between 0 and 100.", file=sys.stderr)
            sys.exit(2)
        from cli import cmd_kill_above
        cmd_kill_above(args.kill_above)

    else:
        # Default: launch TUI
        from collector import Collector
        from analyzer  import Analyzer
        from renderer  import Renderer

        try:
            collector = Collector()
            analyzer  = Analyzer()
            renderer  = Renderer(collector, analyzer)
            curses.wrapper(renderer.run)
        except KeyboardInterrupt:
            pass
        except curses.error as exc:
            print(f"Terminal error: {exc}\n"
                  "Try resizing your terminal or running with a larger window.",
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()