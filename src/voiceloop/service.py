from __future__ import annotations

import json
import os
import plistlib
import subprocess
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.voiceloop.watch"
SERVICE_PATH = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def build_plist(repo_root: Path) -> dict[str, object]:
    python_path = repo_root / ".venv" / "bin" / "python"
    log_path = repo_root / "logs" / "voiceloop_watch.log"
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(python_path), "-u", "-m", "voiceloop", "watch"],
        "WorkingDirectory": str(repo_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"PATH": SERVICE_PATH},
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def _bootout(path: Path) -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _bootstrap(path: Path) -> None:
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        return
    # Fallback for older macOS without bootstrap/bootout
    subprocess.run(["launchctl", "unload", str(path)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["launchctl", "load", "-w", str(path)], check=True)


def install_watch_agent(repo_root: Path, dry_run: bool = False) -> dict[str, object]:
    path = launch_agent_path()
    plist = build_plist(repo_root)
    summary: dict[str, object] = {
        "command": "install-watch",
        "dry_run": dry_run,
        "label": LAUNCH_AGENT_LABEL,
        "plist_path": str(path),
        "plist": plist,
        "user_note": "VoiceLoop watch will start at login and restart automatically if it exits.",
    }
    if dry_run:
        return summary
    if not (repo_root / ".venv" / "bin" / "python").exists():
        raise RuntimeError(f"venv python not found: {repo_root / '.venv' / 'bin' / 'python'}")
    (repo_root / "logs").mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(plist, f)
    _bootout(path)
    _bootstrap(path)
    summary["status"] = "loaded"
    return summary


def remove_watch_agent(dry_run: bool = False) -> dict[str, object]:
    path = launch_agent_path()
    summary: dict[str, object] = {
        "command": "remove-watch",
        "dry_run": dry_run,
        "label": LAUNCH_AGENT_LABEL,
        "plist_path": str(path),
        "existed": path.exists(),
    }
    if dry_run:
        return summary
    _bootout(path)
    if path.exists():
        path.unlink()
    summary["status"] = "removed"
    return summary


def dumps_summary(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True, default=str)
