from datetime import date, timedelta
from pathlib import Path

from voiceloop.weekly import run_weekly


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


def test_weekly_skips_recordings_outside_week(tmp_path):
    data_dir = tmp_path / "data"
    last_week = date.today() - timedelta(days=7)
    monday = last_week - timedelta(days=last_week.weekday())
    folder = data_dir / f"{monday.strftime('%Y%m%d')}_旧录音"
    folder.mkdir(parents=True)
    (folder / f"{folder.name}.md").write_text("# 旧纪要\n", encoding="utf-8")
    result = run_weekly(data_dir, engine="mock")
    assert result["status"] == "skipped"
