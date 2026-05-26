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
    """Collect all meeting markdown files within the week range."""
    files: list[Path] = []
    current = monday
    while current <= sunday:
        day_str = current.strftime("%Y%m%d")
        meetings_dir = data_dir / day_str / "meetings"
        if meetings_dir.exists():
            for path in sorted(meetings_dir.glob("*.md")):
                if path.is_file() and not path.name.startswith("no_meeting"):
                    files.append(path)
        current += timedelta(days=1)
    return files


def _resolve_kimi_api_key() -> str:
    credentials_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
    if credentials_path.exists():
        try:
            data = json.loads(credentials_path.read_text(encoding="utf-8"))
            access_token = data.get("access_token")
            if access_token:
                return str(access_token)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    api_key = os.environ.get("KIMI_API_KEY")
    if api_key:
        return api_key
    raise RuntimeError(
        "Kimi API key not found. Either set KIMI_API_KEY environment variable "
        "or login with 'kimi login' to create ~/.kimi/credentials/kimi-code.json"
    )


def _call_kimi_api(prompt: str, api_key: str, timeout: int = 600) -> str:
    import httpx

    response = httpx.post(
        "https://api.kimi.com/coding/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "KimiCLI/1.44.0",
        },
        json={
            "model": "kimi-latest",
            "messages": [
                {"role": "system", "content": "你是一个工作助手，帮助整理会议纪要周报。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    response_json = response.json()
    message = response_json["choices"][0]["message"]
    return message.get("content", "") or message.get("reasoning_content", "") or ""


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

    api_key = _resolve_kimi_api_key()
    prompt = build_kimi_weekly_prompt(data_dir, week_str)

    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[Kimi Weekly] Generating report (attempt {attempt}/{max_retries})...")
            response_text = _call_kimi_api(prompt, api_key, timeout=600)
            break
        except Exception as exc:
            last_error = exc
            print(f"[Kimi Weekly] Attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"[Kimi Weekly] Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Kimi weekly failed after {max_retries} attempts: {last_error}") from last_error

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
