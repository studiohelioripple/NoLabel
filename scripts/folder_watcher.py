#!/usr/bin/env python3
"""
NoLabel Folder Watcher Daemon
Monitors ~/Documents/Label-Cleaner for newly added media files
and auto-patches corner labels in-place, keeping originals in 'backup/'.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Set

from queue_worker import NoLabelQueue, log_message

DEFAULT_LABEL_DIR = Path.home() / "Documents/Label-Cleaner"
WATCH_DIR = (
    DEFAULT_LABEL_DIR
    if DEFAULT_LABEL_DIR.exists()
    else Path.home() / "Documents/Label-Cleaner"
)
IGNORED_SUBDIRS = {"backup", ".git"}
IGNORED_PREFIXES = {".", "~$", "#"}


class FolderWatcher:
    def __init__(
        self,
        watch_dir: Path = WATCH_DIR,
        poll_interval: float = 1.0,
        inpaint_radius: int = 3,
        method: str = "telea"
    ):
        self.watch_dir = Path(watch_dir).resolve()
        self.poll_interval = poll_interval
        self.running = False
        self.seen_files: Set[str] = set()

        self.queue = NoLabelQueue(
            watch_dir=self.watch_dir,
            backup_dir=self.watch_dir / "backup",
            inpaint_radius=inpaint_radius,
            method=method
        )

    def scan_directory(self) -> None:
        """Scans the watch folder top-level for newly added files."""
        try:
            entries = list(self.watch_dir.iterdir())
        except Exception:
            return

        for entry in entries:
            name = entry.name
            if any(name.startswith(p) for p in IGNORED_PREFIXES):
                continue
            if name in IGNORED_SUBDIRS:
                continue

            # Keynote files are packages/directories ending in .key
            is_key_bundle = entry.is_dir() and name.lower().endswith(".key")
            if not entry.is_file() and not is_key_bundle:
                continue

            entry_str = str(entry.resolve())
            if not self.queue.is_already_processed(entry):
                if entry_str not in self.seen_files:
                    self.seen_files.add(entry_str)
                    self.queue.enqueue(entry)

    def start(self) -> None:
        self.running = True
        self.queue.start()
        log_message(f"Folder watcher active on: {self.watch_dir}")
        print(f"[*] NoLabel Watcher is running on: {self.watch_dir}")
        print("    Auto-patching corner labels in-place. Originals saved to 'backup/'.")
        print("    Press Ctrl+C to stop.")

        self.scan_directory()

        while self.running:
            try:
                time.sleep(self.poll_interval)
                self.scan_directory()
            except KeyboardInterrupt:
                break
            except Exception as e:
                log_message(f"Watcher loop error: {e}")
                time.sleep(self.poll_interval)

        self.stop()

    def stop(self) -> None:
        self.running = False
        self.queue.stop()
        log_message("Folder watcher terminated.")


def handle_signal(sig, frame):
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    parser = argparse.ArgumentParser(description="NoLabel Folder Watcher")
    parser.add_argument("--dir", "-d", type=str, default=str(WATCH_DIR), help="Directory to monitor")
    parser.add_argument("--interval", "-i", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--radius", "-r", type=int, default=3, help="Inpaint neighborhood radius")
    parser.add_argument("--method", "-m", choices=["telea", "ns"], default="telea", help="Inpainting algorithm")

    args = parser.parse_args()

    watcher = FolderWatcher(
        watch_dir=Path(args.dir),
        poll_interval=args.interval,
        inpaint_radius=args.radius,
        method=args.method
    )
    watcher.start()
