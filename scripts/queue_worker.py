#!/usr/bin/env python3
"""
NoLabel FIFO Queue Manager (In-Place Auto-Patching Engine)
- Patches media files in-place in ~/Documents/Label-Cleaner.
- Archives untouched originals in the 'backup' sub-folder.
- Prevents re-trigger loops using an mtime / hash cache.
- Delivers native macOS desktop notifications when complete.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set

from nolabel_core import get_file_type, is_supported_file, process_file

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "queue.log"
CACHE_FILE = BASE_DIR / "logs" / "processed_cache.json"


def log_message(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def send_macos_notification(title: str, message: str) -> None:
    """Displays a native macOS banner notification using osascript."""
    try:
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        cmd = f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True)
    except Exception:
        pass


def wait_until_file_stable(file_path: Path, max_wait: float = 30.0, check_interval: float = 1.0) -> bool:
    """
    Ensures that a file being copied has finished writing and has a stable size.
    """
    if not file_path.exists():
        return False

    start_time = time.time()
    last_size = -1

    while time.time() - start_time < max_wait:
        try:
            if file_path.is_dir():
                current_size = sum(f.stat().st_size for f in file_path.glob("**/*") if f.is_file())
            else:
                current_size = file_path.stat().st_size
        except Exception:
            time.sleep(check_interval)
            continue

        if current_size == last_size and current_size > 0:
            try:
                if not file_path.is_dir():
                    with open(file_path, "rb") as f:
                        f.read(1024)
                return True
            except (IOError, PermissionError):
                time.sleep(check_interval)
                continue

        last_size = current_size
        time.sleep(check_interval)

    return file_path.exists() and last_size > 0


DEFAULT_WATCH_DIR = (
    Path.home() / "Documents/Label-Cleaner"
    if Path.home() / "Documents/Label-Cleaner".exists()
    else Path.home() / "Documents/Label-Cleaner"
)


class NoLabelQueue:
    def __init__(
        self,
        watch_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        inpaint_radius: int = 3,
        method: str = "telea"
    ):
        self.watch_dir = Path(watch_dir or DEFAULT_WATCH_DIR).resolve()
        self.backup_dir = Path(backup_dir or (self.watch_dir / "backup")).resolve()
        self.inpaint_radius = inpaint_radius
        self.method = method

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self.queue: queue.Queue[Path] = queue.Queue()
        self.enqueued_paths: Set[str] = set()
        self.processed_cache: Dict[str, float] = self._load_cache()
        self.lock = threading.Lock()
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False

    def _load_cache(self) -> Dict[str, float]:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self) -> None:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.processed_cache, f)
        except Exception:
            pass

    def is_already_processed(self, file_path: Path) -> bool:
        """Checks if file has already been patched by comparing mtime."""
        key = str(file_path.resolve())
        if key in self.processed_cache:
            try:
                current_mtime = file_path.stat().st_mtime
                if abs(current_mtime - self.processed_cache[key]) < 1.0:
                    return True
            except Exception:
                pass
        return False

    def mark_processed(self, file_path: Path) -> None:
        """Records file mtime to avoid re-triggering loops."""
        try:
            key = str(file_path.resolve())
            self.processed_cache[key] = file_path.stat().st_mtime
            self._save_cache()
        except Exception:
            pass

    def enqueue(self, file_path: Path, force: bool = False) -> bool:
        """Enqueues a file if supported and not already processed/queued."""
        resolved = Path(file_path).resolve()
        if not is_supported_file(resolved):
            return False

        # Exclude backup folder
        if resolved.name == "backup" or "backup" in resolved.parts:
            return False

        if not force and self.is_already_processed(resolved):
            return False

        with self.lock:
            key = str(resolved)
            if key in self.enqueued_paths:
                return False
            self.enqueued_paths.add(key)
            self.queue.put(resolved)
            log_message(f"Enqueued for auto-patching: {resolved.name} (Queue depth: {self.queue.qsize()})")
            return True

    def process_single_file(self, file_path: Path, force: bool = False) -> bool:
        """
        Synchronously processes a single file:
        1. Validates support and stability
        2. Preserves untouched original in <file.parent>/backup/<file.name>
        3. Heals corner label in-place
        4. Updates mtime cache and sends native notification
        """
        resolved = Path(file_path).resolve()
        if not is_supported_file(resolved):
            log_message(f"Skipping unsupported file: {resolved.name}")
            return False

        if resolved.name == "backup" or "backup" in resolved.parts:
            return False

        if not force and self.is_already_processed(resolved):
            log_message(f"Skipping already processed file: {resolved.name}")
            return False

        log_message(f"Starting auto-patch: {resolved.name}")
        if not wait_until_file_stable(resolved):
            log_message(f"Skipping {resolved.name}: file was removed or size did not stabilize.")
            return False

        # 1. Step: Save pristine backup to <file.parent>/backup/<file.name>
        file_backup_dir = resolved.parent / "backup"
        file_backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dest = file_backup_dir / resolved.name
        try:
            if resolved.is_dir():
                if backup_dest.exists():
                    shutil.rmtree(backup_dest)
                shutil.copytree(resolved, backup_dest)
            else:
                shutil.copy2(resolved, backup_dest)
            log_message(f"  [+] Backup saved to: {backup_dest}")
        except Exception as e:
            log_message(f"  [!] Backup warning: {e}")

        # 2. Step: Patch in-place
        is_dir_pkg = resolved.is_dir()
        if is_dir_pkg:
            # Keynote package
            success = process_file(
                input_path=resolved,
                output_path=resolved,
                archive_dir=None,
                inpaint_radius=self.inpaint_radius,
                method=self.method,
                verbose=True
            )
        else:
            with tempfile.NamedTemporaryFile(suffix=resolved.suffix, delete=False) as tmp_out:
                tmp_out_path = Path(tmp_out.name)

            try:
                success = process_file(
                    input_path=resolved,
                    output_path=tmp_out_path,
                    archive_dir=None,
                    inpaint_radius=self.inpaint_radius,
                    method=self.method,
                    verbose=True
                )

                if success and tmp_out_path.exists() and tmp_out_path.stat().st_size > 0:
                    tmp_out_path.replace(resolved)
                elif tmp_out_path.exists():
                    tmp_out_path.unlink()
            except Exception as pe:
                if tmp_out_path.exists():
                    tmp_out_path.unlink()
                raise pe

        if success:
            self.mark_processed(resolved)
            log_message(f"  [✓] Auto-patched in-place: {resolved.name}")
            send_macos_notification(
                title="NoLabel Auto-Patched",
                message=f"Cleaned corner label in {resolved.name} (original in backup/)"
            )
            return True
        else:
            log_message(f"  [-] Skipped or no label to patch: {resolved.name}")
            return False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.worker_thread.start()
        log_message("NoLabel queue worker started.")

    def stop(self) -> None:
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=3.0)
        log_message("NoLabel queue worker stopped.")

    def _process_loop(self) -> None:
        while self.running:
            try:
                file_path = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self.process_single_file(file_path, force=False)
            except Exception as e:
                log_message(f"Unexpected error auto-patching {file_path.name}: {e}")
            finally:
                with self.lock:
                    self.enqueued_paths.discard(str(file_path))
                self.queue.task_done()

