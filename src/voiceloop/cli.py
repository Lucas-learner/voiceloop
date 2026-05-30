from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import DEFAULT_SOURCE_DIR, load_config
from .cron import append_cron, remove_managed_cron
from .postprocess import run_minutes
from .rename import is_default_named, rename_with_topic
from .sync import recording_day, rename_synced_copy, sync_single_file, sync_voice_memos
from .watch import process_new_recording, start_watch
from .weekly import run_weekly
from .asr import run_asr, run_asr_for_file


def today() -> str:
    return datetime.now().strftime("%Y%m%d")


def json_print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default=None, help=f"Voice Memos source directory. Default: {DEFAULT_SOURCE_DIR}")
    parser.add_argument("--data-dir", default=None, help="Local data directory. Default: ./data")
    parser.add_argument("--repo-root", default=None, help="Repository root. Default: installed package repository root")
    parser.add_argument("--sync-dir", default=None, help="Cloud sync directory for meeting minutes. Default: ~/Library/Mobile Documents/com~apple~CloudDocs/数据同步/voiceloop")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voiceloop", description="VoiceLoop - AI meeting minutes from voice memos")
    parser.add_argument("--version", action="version", version=f"voiceloop {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # watch - Start file watcher
    watch = subparsers.add_parser("watch", help="Watch Voice Memos directory for new recordings")
    add_common_paths(watch)
    watch.add_argument("--asr-engine", choices=["mock", "mlx", "api"], default="mlx", help="ASR engine (default: mlx)")
    watch.add_argument("--minutes-engine", choices=["mock", "codex", "kimi"], default="kimi", help="Minutes engine (default: kimi)")

    # process-file - Manually process a single recording
    proc = subparsers.add_parser("process-file", help="Process a single audio file")
    proc.add_argument("path", help="Path to the audio file")
    add_common_paths(proc)
    proc.add_argument("--asr-engine", choices=["mock", "mlx", "api"], default="mlx")
    proc.add_argument("--minutes-engine", choices=["mock", "codex", "kimi"], default="kimi")

    # weekly - Generate weekly report
    weekly = subparsers.add_parser("weekly", help="Generate weekly report from meeting minutes")
    add_common_paths(weekly)
    weekly.add_argument("--date", default=None, help="ISO week like 2026W21. Default: current week")
    weekly.add_argument("--engine", choices=["mock", "kimi"], default="kimi", help="Weekly report engine (default: kimi)")

    # doctor - Check environment
    doctor = subparsers.add_parser("doctor", help="Check local environment and paths")
    add_common_paths(doctor)

    # install-cron - Install weekly cron
    cron = subparsers.add_parser("install-cron", help="Set up the optional weekly cron job")
    add_common_paths(cron)
    cron.add_argument("--dry-run", action="store_true")
    cron.add_argument("--day", default="fri", help="Day of week to run weekly report. Default: fri. Options: sun, mon, tue, wed, thu, fri, sat or 0-6")

    # remove-cron - Remove cron
    rm_cron = subparsers.add_parser("remove-cron", help="Remove the weekly cron job")
    add_common_paths(rm_cron)
    rm_cron.add_argument("--dry-run", action="store_true")

    # Legacy batch commands (for manual use)
    sync_cmd = subparsers.add_parser("sync", help="Copy voice memos into dated folders")
    add_common_paths(sync_cmd)
    sync_cmd.add_argument("--date", default=None, help="Limit sync to one day as YYYYMMDD")
    sync_cmd.add_argument("--dry-run", action="store_true")

    asr_cmd = subparsers.add_parser("asr", help="Transcribe one day of audio")
    add_common_paths(asr_cmd)
    asr_cmd.add_argument("--date", default=today(), help="Day to transcribe as YYYYMMDD")
    asr_cmd.add_argument("--engine", choices=["mock", "mlx"], default="mlx")
    asr_cmd.add_argument("--mock-text", default=None)

    minutes_cmd = subparsers.add_parser("minutes", help="Generate meeting minutes for one day")
    add_common_paths(minutes_cmd)
    minutes_cmd.add_argument("--date", default=today(), help="Day as YYYYMMDD")
    minutes_cmd.add_argument("--engine", choices=["mock", "codex", "kimi"], default="kimi")

    return parser


def doctor_payload(source: str | None = None, data_dir: str | None = None, repo_root: str | None = None) -> dict[str, object]:
    config = load_config(source, data_dir, repo_root)
    data_parent = config.data_dir if config.data_dir.exists() else config.data_dir.parent
    checks = {
        "source_exists": config.source_dir.exists(),
        "source_is_voice_memos_default": str(config.source_dir) == str(Path(DEFAULT_SOURCE_DIR).expanduser().resolve()),
        "data_parent_exists": data_parent.exists(),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "codex_available": shutil.which("codex") is not None,
        "kimi_available": shutil.which("kimi") is not None,
        "kimi_credentials": (Path.home() / ".kimi" / "credentials" / "kimi-code.json").exists(),
        "watchdog_available": _check_watchdog(),
    }
    return {
        "command": "doctor",
        "status": "ok" if checks["data_parent_exists"] else "warning",
        "repo_root": str(config.repo_root),
        "source_dir": str(config.source_dir),
        "data_dir": str(config.data_dir),
        "checks": checks,
    }


def _check_watchdog() -> bool:
    try:
        import watchdog  # noqa: F401
        return True
    except ImportError:
        return False


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_config(args.source, args.data_dir, args.repo_root)

    if args.command == "doctor":
        return doctor_payload(args.source, args.data_dir, args.repo_root)

    if args.command == "watch":
        return start_watch(config.source_dir, config.data_dir, asr_engine=args.asr_engine, minutes_engine=args.minutes_engine, sync_dir=config.sync_dir)

    if args.command == "process-file":
        source_path = Path(args.path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"File not found: {source_path}")
        return process_new_recording(
            source_path,
            config.data_dir,
            asr_engine=args.asr_engine,
            minutes_engine=args.minutes_engine,
            sync_dir=config.sync_dir,
        )

    if args.command == "weekly":
        return run_weekly(config.data_dir, week_str=args.date, engine=args.engine, sync_dir=config.sync_dir)

    if args.command == "install-cron":
        return append_cron(config.repo_root, dry_run=args.dry_run, day_of_week=args.day)

    if args.command == "remove-cron":
        return remove_managed_cron(config.repo_root, dry_run=args.dry_run)

    if args.command == "sync":
        return sync_voice_memos(config.source_dir, config.data_dir, dry_run=args.dry_run, day=args.date)

    if args.command == "asr":
        return run_asr(config.data_dir, args.date, engine=args.engine, mock_text=args.mock_text)

    if args.command == "minutes":
        return run_minutes(config.data_dir, args.date, engine=args.engine)

    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        json_print(run(args))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
