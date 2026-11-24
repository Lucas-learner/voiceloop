from datetime import date, timedelta
from pathlib import Path

from voiceloop.weekly import build_kimi_weekly_prompt, last_week_label, run_weekly, week_range


def test_last_week_label_matches_previous_week():
    label = last_week_label()
    monday, sunday = week_range(label)
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    assert sunday == current_monday - timedelta(days=1)
    assert monday == current_monday - timedelta(days=7)


def test_weekly_skips_when_no_recordings(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    result = run_weekly(data_dir, engine="mock")
    assert result["status"] == "skipped"
    assert result["meeting_count"] == 0
    assert result["output_path"] is None
    weekly_dir = tmp_path / "weekly"
    assert not list(weekly_dir.glob("*.md")) if weekly_dir.exists() else True


def test_weekly_generates_when_recordings_exist(tmp_path):
    data_dir = tmp_path / "data"
    today = date.today()
    folder = data_dir / f"{today.strftime('%Y%m%d')}_测试主题"
    folder.mkdir(parents=True)
    (folder / f"{folder.name}.md").write_text("# 测试纪要\n", encoding="utf-8")
    result = run_weekly(data_dir, engine="mock")
    assert result["meeting_count"] == 1
    assert Path(result["output_path"]).exists()


def test_weekly_prompt_includes_minutes_once_without_transcript(tmp_path):
    data_dir = tmp_path / "data"
    folder = data_dir / f"{date.today():%Y%m%d}_测试主题"
    folder.mkdir(parents=True)
    (folder / f"{folder.name}.md").write_text("正式纪要", encoding="utf-8")
    (folder / f"{folder.name}_transcript.md").write_text("转录全文", encoding="utf-8")
    prompt = build_kimi_weekly_prompt(data_dir)
    assert prompt.count("正式纪要") == 1
    assert "转录全文" not in prompt


def test_weekly_skips_recordings_outside_week(tmp_path):
    data_dir = tmp_path / "data"
    last_week = date.today() - timedelta(days=7)
    monday = last_week - timedelta(days=last_week.weekday())
    folder = data_dir / f"{monday.strftime('%Y%m%d')}_旧录音"
    folder.mkdir(parents=True)
    (folder / f"{folder.name}.md").write_text("# 旧纪要\n", encoding="utf-8")
    result = run_weekly(data_dir, engine="mock")
    assert result["status"] == "skipped"
