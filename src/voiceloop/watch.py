from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


def is_icloud_placeholder(path: Path) -> bool:
    """Check if file is an iCloud placeholder (ends with .icloud or has xattr com.apple.icloud.itemName)."""
    if path.suffix == ".icloud":
        return True
    # Check for extended attribute (com.apple.icloud.itemName)
    import subprocess
    try:
        result = subprocess.run(
            ["xattr", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "com.apple.icloud.itemName" in result.stdout:
            return True
    except Exception:
        pass
    return False


def wait_for_file_ready(path: Path, timeout: int = 120, check_interval: float = 1.0) -> bool:
    """Wait for an iCloud file to be fully downloaded and stable.

    Returns True if file is ready, False if timed out.
    """
    start = time.time()
    last_size = -1
    stable_count = 0

    while time.time() - start < timeout:
        if not path.exists():
            time.sleep(check_interval)
            continue

        if is_icloud_placeholder(path):
            print(f"[Watch] Waiting for iCloud download: {path.name}", file=sys.stderr)
            time.sleep(check_interval)
            continue

        current_size = path.stat().st_size
        if current_size == last_size and current_size > 0:
            stable_count += 1
            if stable_count >= 3:  # File stable for 3 checks
                print(f"[Watch] File ready: {path.name} ({current_size} bytes)", file=sys.stderr)
                return True
        else:
            stable_count = 0
            last_size = current_size
            if current_size > 0:
                print(f"[Watch] File downloading: {path.name} ({current_size} bytes)", file=sys.stderr)

        time.sleep(check_interval)

    print(f"[Watch] Timeout waiting for file: {path.name}", file=sys.stderr)
    return False


def process_new_recording(
    source_path: Path,
    data_dir: Path,
    asr_engine: str = "mlx",
    minutes_engine: str = "kimi",
) -> dict[str, object]:
    """Process a single new recording: sync -> ASR -> minutes -> rename."""
    from .asr import run_asr_for_file
    from .postprocess import run_minutes
    from .rename import is_default_named, rename_with_topic
    from .sync import recording_day, rename_synced_copy, sync_single_file

    print(f"[Watch] Processing: {source_path.name}", file=sys.stderr)

    # 1. Sync
    dest_path = sync_single_file(source_path, data_dir)
    print(f"[Watch] Synced to: {dest_path}", file=sys.stderr)

    # 2. ASR (single file, append to day's transcript)
    day = recording_day(source_path)
    asr_result = run_asr_for_file(dest_path, data_dir, day, engine=asr_engine)
    row_count = len(asr_result)
    print(f"[Watch] ASR: {row_count} rows transcribed", file=sys.stderr)

    # 3. Generate meeting minutes
    day = recording_day(source_path)
    minutes_result = run_minutes(data_dir, day, engine=minutes_engine, audio_files=[dest_path])
    print(f"[Watch] Minutes: {minutes_result.get('outputs', [])}", file=sys.stderr)

    # 4. Rename synced copy only (never rename original Voice Memos file
    # to avoid iCloud sync conflicts — iOS display name is metadata, not filename)
    topic = minutes_result.get("topic")
    renamed_dest = None
    if topic and is_default_named(source_path):
        try:
            renamed_dest = rename_synced_copy(dest_path, topic)
            print(f"[Watch] Renamed sync copy: {renamed_dest.name}", file=sys.stderr)
        except Exception as exc:
            print(f"[Watch] Rename failed: {exc}", file=sys.stderr)

    return {
        "command": "process-file",
        "source": str(source_path),
        "destination": str(dest_path),
        "day": day,
        "asr_rows": row_count,
        "minutes_engine": minutes_engine,
        "topic": topic,
        "renamed_source": None,
        "renamed_destination": str(renamed_dest) if renamed_dest else None,
    }


def start_watch(
    source_dir: Path,
    data_dir: Path,
    asr_engine: str = "mlx",
    minutes_engine: str = "kimi",
) -> dict[str, object]:
    """Start watching the source directory for new voice memos.

    This blocks until interrupted.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    except ImportError:
        raise RuntimeError(
            "watchdog is required for file watching. "
            "Install it with: uv pip install watchdog"
        )

    # Track files currently being processed to avoid duplicates
    _processing: set[str] = set()

    class VoiceMemoHandler(FileSystemEventHandler):
        def on_created(self, event: Any) -> None:
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in (".m4a", ".qta"):
                return

            # Skip if already processing
            path_str = str(path.resolve())
            if path_str in _processing:
                return

            _processing.add(path_str)
            try:
                print(f"[Watch] New file detected: {path.name}", file=sys.stderr)

                # Wait for file to be fully available
                if not wait_for_file_ready(path):
                    print(f"[Watch] Skipping (not ready): {path.name}", file=sys.stderr)
                    return

                # Process the file
                result = process_new_recording(
                    path,
                    data_dir,
                    asr_engine=asr_engine,
                    minutes_engine=minutes_engine,
                )
                print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
            except Exception as exc:
                print(f"[Watch] Error processing {path.name}: {exc}", file=sys.stderr)
            finally:
                _processing.discard(path_str)

    observer = Observer()
    handler = VoiceMemoHandler()
    observer.schedule(handler, str(source_dir), recursive=False)
    observer.start()

    print(f"[Watch] Watching {source_dir} for new voice memos...")
    print(f"[Watch] ASR engine: {asr_engine}, Minutes engine: {minutes_engine}")
    print("[Watch] Press Ctrl+C to stop.")

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        print("\n[Watch] Stopping...", file=sys.stderr)
    finally:
        observer.stop()
        observer.join()

    return {
        "command": "watch",
        "status": "stopped",
        "source_dir": str(source_dir),
        "data_dir": str(data_dir),
    }


def dumps_summary(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
