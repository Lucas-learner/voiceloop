from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".m4a", ".qta"}


@dataclass(frozen=True)
class SyncItem:
    source: str
    destination: str
    action: str
    reason: str


def recording_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def _parse_filename_date(path: Path) -> datetime | None:
    """Parse YYYYMMDD HHMMSS from Voice Memos filename like '20260522 100732-CF347703.m4a'."""
    import re
    match = re.match(r"(\d{8})\s+(\d{6})", path.name)
    if match:
        try:
            return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def recording_day(path: Path) -> str:
    filename_date = _parse_filename_date(path)
    if filename_date:
        return filename_date.strftime("%Y%m%d")
    return recording_timestamp(path).strftime("%Y%m%d")


def destination_for(source: Path, data_dir: Path) -> Path:
    filename_date = _parse_filename_date(source)
    if filename_date:
        stamp = filename_date
    else:
        stamp = recording_timestamp(source)
    day = stamp.strftime("%Y%m%d")
    name = f"{stamp.strftime('%Y%m%d_%H%M')}_watch.m4a"
    return data_dir / day / name


def discover_voice_memos(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        return []
    files = [path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
    return sorted(files, key=lambda item: (item.stat().st_mtime, str(item)))


def build_sync_plan(source_dir: Path, data_dir: Path, day: str | None = None) -> list[SyncItem]:
    items: list[SyncItem] = []
    for source in discover_voice_memos(source_dir):
        if day is not None and recording_day(source) != day:
            continue
        destination = destination_for(source, data_dir)
        if destination.exists():
            action = "skip"
            reason = "destination exists"
        elif source.suffix.lower() == ".qta":
            action = "convert"
            reason = "qta source requires m4a conversion"
        else:
            action = "copy"
            reason = "new m4a source"
        items.append(SyncItem(str(source), str(destination), action, reason))
    return items


def execute_sync_plan(plan: list[SyncItem], dry_run: bool = False) -> list[SyncItem]:
    if dry_run:
        return plan
    executed: list[SyncItem] = []
    for item in plan:
        if item.action == "skip":
            executed.append(item)
            continue
        source = Path(item.source)
        destination = Path(item.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if item.action == "copy":
            shutil.copy2(source, destination)
        elif item.action == "convert":
            convert_qta_to_m4a(source, destination)
        else:
            raise ValueError(f"unknown sync action: {item.action}")
        executed.append(item)
    return executed


def convert_qta_to_m4a(source: Path, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("syncing .qta files requires ffmpeg so the output is a real .m4a file")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-c:a", "aac", str(destination)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def sync_single_file(source_path: Path, data_dir: Path) -> Path:
    """Sync a single audio file to the data directory.

    Returns the destination path.
    """
    destination = destination_for(source_path, data_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    if source_path.suffix.lower() == ".qta":
        convert_qta_to_m4a(source_path, destination)
    else:
        shutil.copy2(source_path, destination)
    return destination


def rename_synced_copy(dest_path: Path, topic: str) -> Path:
    """Rename the synced copy to include the topic."""
    from .rename import sanitize_topic
    date_prefix = dest_path.stem[:8]
    safe_topic = sanitize_topic(topic)
    new_name = f"{date_prefix}_{safe_topic}.m4a"
    new_path = dest_path.with_name(new_name)
    counter = 1
    original_new_path = new_path
    while new_path.exists() and new_path != dest_path:
        new_name = f"{date_prefix}_{safe_topic}_{counter}.m4a"
        new_path = dest_path.with_name(new_name)
        counter += 1
        if counter > 100:
            raise RuntimeError(f"Too many filename collisions for {dest_path}")
    dest_path.rename(new_path)
    return new_path


def sync_voice_memos(source_dir: Path, data_dir: Path, dry_run: bool = False, day: str | None = None) -> dict[str, object]:
    plan = build_sync_plan(source_dir, data_dir, day=day)
    execute_sync_plan(plan, dry_run=dry_run)
    counts = {"copy": 0, "convert": 0, "skip": 0}
    for item in plan:
        counts[item.action] = counts.get(item.action, 0) + 1
    return {
        "command": "sync",
        "dry_run": dry_run,
        "source_dir": str(source_dir),
        "data_dir": str(data_dir),
        "day": day,
        "counts": counts,
        "items": [asdict(item) for item in plan],
    }


def sync_file_to_cloud(source_file: Path, sync_dir: Path | None) -> Path | None:
    """Copy a single file to the cloud sync directory.

    Returns the destination path if synced, None if skipped.
    """
    if sync_dir is None or not source_file.exists():
        return None
    sync_dir.mkdir(parents=True, exist_ok=True)
    dest = sync_dir / source_file.name
    shutil.copy2(source_file, dest)
    return dest


def sync_minutes_to_cloud(final_dir: Path, sync_dir: Path | None) -> Path | None:
    """Copy the meeting minutes markdown to the cloud sync directory.

    Returns the destination path if synced, None if skipped.
    """
    if sync_dir is None:
        return None

    md_files = [f for f in final_dir.iterdir() if f.is_file() and f.suffix == ".md"]
    if not md_files:
        return None

    md_file = md_files[0]
    sync_dir.mkdir(parents=True, exist_ok=True)
    dest = sync_dir / md_file.name
    shutil.copy2(md_file, dest)
    return dest


def dumps_summary(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
