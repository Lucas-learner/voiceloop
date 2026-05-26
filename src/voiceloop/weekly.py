from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_weekly_prompt_template() -> str:
    path = repo_root() / "prompts" / "weekly.md"
    if not path.exists():
        raise FileNotFoundError(f"Weekly prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def week_range(week_str: str | None = None) -> tuple[date, date]:
    """Return (monday, sunday) for the given ISO week string like '2026W21'.

    If week_str is None, returns the current week.
    """
    if week_str is None:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return monday, sunday

    match = re.match(r"(\d{4})W(\d{2})", week_str)
    if not match:
        raise ValueError(f"week must be YYYYWww format, got: {week_str}")
    year, week = int(match.group(1)), int(match.group(2))
    # ISO week: Monday is the first day
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def collect_meeting_files(data_dir: Path, monday: date, sunday: date) -> list[Path]:
    """Collect all meeting markdown files within the week range.

    New layout: each recording has its own folder named YYYYMMDD_主题/,
    containing YYYYMMDD_主题.md (the meeting minutes).
    """
    files: list[Path] = []
    for folder in data_dir.iterdir():
        if not folder.is_dir() or folder.name.startswith("tmp_"):
            continue
        # Parse date prefix from folder name: YYYYMMDD_...
        day_match = re.match(r"(\d{8})_", folder.name)
        if not day_match:
            continue
        try:
            folder_date = datetime.strptime(day_match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if monday <= folder_date <= sunday:
            for path in sorted(folder.glob("*.md")):
                if path.is_file():
                    files.append(path)
    return files


def build_kimi_weekly_prompt(data_dir: Path, week_str: str | None = None) -> str:
    monday, sunday = week_range(week_str)
    files = collect_meeting_files(data_dir, monday, sunday)
    template = load_weekly_prompt_template()

    # Build content from all meeting files
    contents = []
    for f in files:
        day = f.parent.parent.name  # YYYYMMDD
        contents.append(f"## 会议文件: {day}/{f.name}\n\n{f.read_text(encoding='utf-8')}\n")

    all_content = "\n".join(contents) if contents else "本周暂无会议纪要。"

    week_label = week_str or f"{monday.strftime('%Y%m%d')}-{sunday.strftime('%Y%m%d')}"

    return "\n".join([
        "你是一个 AI 助手，帮助整理会议纪要周报。",
        "",
        "## Prompt Template",
        template.strip(),
        "",
        f"## Week: {week_label}",
        f"## Range: {monday.isoformat()} to {sunday.isoformat()}",
        "",
        "## Input Meeting Minutes",
        all_content,
        "",
        "## Output Instructions",
        "请直接输出周报内容，使用 Markdown 格式。输出语言为中文。",
        "周报应包含：",
        "- 本周概览",
        "- 各会议要点回顾",
        "- 决策汇总",
        "- 待办跟踪",
        "- 下周关注点",
        "",
        "Guardrails:",
        "- 不编造事实、参与者或决策。",
        "- 对不确定的事项标记为待确认。",
        "- 所有输出使用中文。",
    ])


def run_kimi_weekly(data_dir: Path, week_str: str | None = None) -> dict[str, object]:
    monday, sunday = week_range(week_str)
    week_label = week_str or f"{monday.isocalendar()[0]}W{monday.isocalendar()[1]:02d}"

    weekly_dir = data_dir.parent / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    output_path = weekly_dir / f"weekly_{week_label}.md"

    from .kimi_client import call_kimi_api_with_retry, resolve_kimi_config

    api_key, base_url = resolve_kimi_config()
    prompt = build_kimi_weekly_prompt(data_dir, week_str)
    print(f"[Kimi Weekly] Generating report (base_url: {base_url})...")
    response_text = call_kimi_api_with_retry(
        prompt, api_key, base_url=base_url,
        system_message="你是一个工作助手，帮助整理会议纪要周报。",
        timeout=600,
    )

    output_path.write_text(response_text, encoding="utf-8")

    files = collect_meeting_files(data_dir, monday, sunday)
    return {
        "command": "weekly",
        "engine": "kimi",
        "week": week_label,
        "range": f"{monday.isoformat()} to {sunday.isoformat()}",
        "meeting_count": len(files),
        "output_path": str(output_path),
    }


def run_mock_weekly(data_dir: Path, week_str: str | None = None) -> dict[str, object]:
    monday, sunday = week_range(week_str)
    week_label = week_str or f"{monday.isocalendar()[0]}W{monday.isocalendar()[1]:02d}"
    weekly_dir = data_dir.parent / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    output_path = weekly_dir / f"weekly_{week_label}.md"

    content = f"# 周报 {week_label}\n\n这是 mock 生成的周报。\n\n## 本周概览\n\n暂无内容。\n"
    output_path.write_text(content, encoding="utf-8")

    files = collect_meeting_files(data_dir, monday, sunday)
    return {
        "command": "weekly",
        "engine": "mock",
        "week": week_label,
        "range": f"{monday.isoformat()} to {sunday.isoformat()}",
        "meeting_count": len(files),
        "output_path": str(output_path),
    }


def run_weekly(data_dir: Path, week_str: str | None = None, engine: str = "mock") -> dict[str, object]:
    if engine == "mock":
        return run_mock_weekly(data_dir, week_str)
    if engine == "kimi":
        return run_kimi_weekly(data_dir, week_str)
    raise ValueError(f"unsupported weekly engine: {engine}")


def dumps_summary(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
