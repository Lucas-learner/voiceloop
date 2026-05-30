from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SOURCE_DIR = "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/"
DEFAULT_SYNC_DIR = "~/Library/Mobile Documents/com~apple~CloudDocs/数据同步/voiceloop"


@dataclass(frozen=True)
class VoiceLoopConfig:
    source_dir: Path
    data_dir: Path
    repo_root: Path
    sync_dir: Path | None = None


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def load_config(
    source_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    sync_dir: str | Path | None = None,
) -> VoiceLoopConfig:
    root = expand_path(repo_root or os.environ.get("VOICELOOP_REPO_ROOT") or package_root())
    source = expand_path(source_dir or os.environ.get("VOICELOOP_SOURCE_DIR") or DEFAULT_SOURCE_DIR)
    data = expand_path(data_dir or os.environ.get("VOICELOOP_DATA_DIR") or root / "data")
    sync_raw = sync_dir or os.environ.get("VOICELOOP_SYNC_DIR") or DEFAULT_SYNC_DIR
    sync = expand_path(sync_raw) if sync_raw else None
    return VoiceLoopConfig(source_dir=source, data_dir=data, repo_root=root, sync_dir=sync)
