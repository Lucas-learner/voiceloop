from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def compress_audio_if_needed(audio_path: Path, bitrate_threshold: int = 128000) -> Path:
    """Compress audio to 64 kbps mono AAC if bitrate exceeds threshold.

    Uses ffprobe to detect bitrate and ffmpeg to transcode.
    Returns the path to the (possibly compressed) audio file.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return audio_path

    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(audio_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        info = json.loads(result.stdout)
        bitrate = int(info.get("format", {}).get("bit_rate", 0))
    except (json.JSONDecodeError, ValueError, TypeError, subprocess.TimeoutExpired):
        return audio_path

    if bitrate <= bitrate_threshold:
        return audio_path

    # Compress to 64 kbps mono AAC
    output = audio_path.with_suffix(".m4a")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(audio_path), "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-ar", "48000", str(output)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[Watch] Audio compression failed: {exc}", file=sys.stderr)
        return audio_path

    # Remove original large file, keep compressed
    if output != audio_path:
        audio_path.unlink()
        print(f"[Watch] Compressed audio: {bitrate // 1000} kbps → 64 kbps mono AAC ({output.name})", file=sys.stderr)
    return output


def is_icloud_placeholder(path: Path) -> bool:
    """Check if file is an iCloud placeholder (ends with .icloud or has xattr com.apple.icloud.itemName)."""
    if path.suffix == ".icloud":
        return True
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
            if stable_count >= 3:
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
    sync_dir: Path | None = None,
) -> dict[str, object]:
    """Process a single new recording into its own folder: YYYYMMDD_主题/.

    Pipeline:
      1. Copy audio to a temp folder under data/
      2. ASR -> transcript.csv
      3. AI minutes -> meeting.md + topic
      4. Rename temp folder to YYYYMMDD_主题/
      5. Rename files inside to match folder name
    """
    from .asr import run_asr_for_file_to_dir
    from .postprocess import run_minutes_for_dir
    from .rename import sanitize_topic
    from .sync import recording_day, recording_timestamp, sync_minutes_to_cloud

    # Build a temporary working directory
    day = recording_day(source_path)
    ts = recording_timestamp(source_path).strftime("%Y%m%d_%H%M%S")
    temp_name = f"tmp_{ts}"
    temp_dir = data_dir / temp_name
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Copy audio into temp dir
    temp_audio = temp_dir / source_path.name
    shutil.copy2(source_path, temp_audio)
    print(f"[Watch] Copied to temp: {temp_audio}", file=sys.stderr)

    # Compress if high bitrate (e.g., Voice Memos lossless recordings)
    temp_audio = compress_audio_if_needed(temp_audio)

    # ASR
    asr_rows = run_asr_for_file_to_dir(temp_audio, temp_dir, engine=asr_engine)
    print(f"[Watch] ASR: {len(asr_rows)} rows", file=sys.stderr)

    # Minutes -> get topic
    minutes_result = run_minutes_for_dir(temp_dir, engine=minutes_engine)
    topic = minutes_result.get("topic")
    print(f"[Watch] Minutes topic: {topic}", file=sys.stderr)

    # Determine final folder name
    if topic:
        final_base = f"{day}_{sanitize_topic(topic)}"
    else:
        final_base = ts

    final_dir = data_dir / final_base
    counter = 1
    original_base = final_base
    while final_dir.exists():
        final_base = f"{original_base}_{counter}"
        final_dir = data_dir / final_base
        counter += 1
        if counter > 100:
            raise RuntimeError(f"Too many folder collisions for {original_base}")

    # Rename temp dir -> final dir
    temp_dir.rename(final_dir)
    print(f"[Watch] Final folder: {final_dir.name}", file=sys.stderr)

    # Rename files inside to match folder name
    for file in final_dir.iterdir():
        if file.is_file() and file.suffix in (".m4a", ".csv", ".md"):
            new_name = f"{final_base}{file.suffix}"
            file.rename(final_dir / new_name)

    # Sync meeting minutes to cloud directory
    synced_path = sync_minutes_to_cloud(final_dir, sync_dir)
    if synced_path:
        print(f"[Watch] Synced minutes to: {synced_path}", file=sys.stderr)

    return {
        "command": "process-file",
        "source": str(source_path),
        "final_dir": str(final_dir),
        "day": day,
        "asr_rows": len(asr_rows),
        "minutes_engine": minutes_engine,
        "topic": topic,
        "synced_path": str(synced_path) if synced_path else None,
    }


def start_watch(
    source_dir: Path,
    data_dir: Path,
    asr_engine: str = "mlx",
    minutes_engine: str = "kimi",
    sync_dir: Path | None = None,
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
                    sync_dir=sync_dir,
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
