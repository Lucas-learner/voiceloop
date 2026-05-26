from __future__ import annotations

import re
from pathlib import Path

# Default iOS Voice Memos filename pattern: "20260522 100732-CF347703.m4a"
DEFAULT_NAME_PATTERN = re.compile(r"^\d{8}\s+\d{6}-[A-F0-9]+\.m4a$")

# Extract date prefix from default filename like "20260522 100732-xxx.m4a"
def _extract_date_prefix(path: Path) -> str:
    match = re.match(r"(\d{8})", path.name)
    if match:
        return match.group(1)
    return path.stem[:8]


def is_default_named(path: Path) -> bool:
    """Check if the file has the default iOS Voice Memos naming pattern."""
    return bool(DEFAULT_NAME_PATTERN.match(path.name))


def sanitize_topic(topic: str, max_length: int = 30) -> str:
    """Sanitize topic for use in filename."""
    # Remove characters that are problematic in filenames
    sanitized = re.sub(r'[<>:"/\\|?*]', "", topic)
    sanitized = sanitized.strip()
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    return sanitized


def rename_with_topic(path: Path, topic: str) -> Path:
    """Rename a file to YYYYMMDD_Topic.m4a format.

    Args:
        path: Path to the file to rename.
        topic: The topic/title extracted from the minutes.

    Returns:
        The new path after renaming.
    """
    date_prefix = _extract_date_prefix(path)
    safe_topic = sanitize_topic(topic)
    new_name = f"{date_prefix}_{safe_topic}.m4a"
    new_path = path.with_name(new_name)

    # Handle collision
    counter = 1
    original_new_path = new_path
    while new_path.exists() and new_path != path:
        new_name = f"{date_prefix}_{safe_topic}_{counter}.m4a"
        new_path = path.with_name(new_name)
        counter += 1
        if counter > 100:
            raise RuntimeError(f"Too many filename collisions for {path}")

    path.rename(new_path)
    return new_path
