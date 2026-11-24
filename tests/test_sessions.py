from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from voiceloop import sessions, watch
from voiceloop.cli import build_parser, run
from voiceloop.weekly import collect_meeting_files


def add_part(data_dir, name, start, duration, text, valid=True):
    folder = data_dir / name
    folder.mkdir(parents=True)
    (folder / f"{name}_transcript.md").write_text(text, encoding="utf-8")
    (folder / f"{name}.md").write_text("原纪要：" + text, encoding="utf-8")
    audio = folder / f"{name}.m4a"
    audio.write_bytes(name.encode())
    rid = sessions.source_id(audio)
    sessions.register_recording(data_dir, folder, rid, {
        "source_name": f"{name}.m4a", "start": start.isoformat() if start else None,
        "end": (start + timedelta(seconds=duration)).isoformat() if start and duration else None,
        "duration": duration,
    }, valid)
    return rid, folder


@pytest.fixture
def start():
    return datetime(2026, 11, 10, 14, tzinfo=timezone(timedelta(hours=8)))


@pytest.fixture
def notes(monkeypatch):
    calls = []

    def generate(folder, engine="mock"):
        transcript = (folder / "transcript.md").read_text(encoding="utf-8")
        calls.append(transcript)
        (folder / "meeting.md").write_text("统一纪要\n" + transcript, encoding="utf-8")
        return {"topic": "统一主题", "has_content": True}

    monkeypatch.setattr("voiceloop.postprocess.run_minutes_for_dir", generate)
    return calls


def test_duration_gap_late_long_recording_and_incremental_update(tmp_path, start, monkeypatch, notes):
    a, folder = add_part(tmp_path, "20261110_A", start, 35 * 60, "甲项目的问题是")
    b, other = add_part(tmp_path, "20261110_B", start + timedelta(minutes=37), 60 * 60, "刚才的问题，答案是乙")
    seen = []
    monkeypatch.setattr(sessions, "judge_continuation", lambda x, y, gap, engine: seen.append((x, y, gap)) or True)

    result = sessions.auto_merge(tmp_path, b, "api")
    assert result["final_dir"] == str(folder)
    assert result["part_count"] == 2
    assert seen == [("甲项目的问题是", "刚才的问题，答案是乙", 120)]
    assert (other / sessions.RAW_TRANSCRIPT).read_text() == "刚才的问题，答案是乙"
    assert (folder / sessions.RAW_TRANSCRIPT).read_text() == "甲项目的问题是"
    assert "间隔约 120 秒" in notes[0]
    assert notes[0].index("甲项目的问题是") < notes[0].index("刚才的问题，答案是乙")

    c, _ = add_part(tmp_path, "20261110_C", start + timedelta(minutes=99), 20 * 60, "最后确认由丙跟进")
    assert sessions.auto_merge(tmp_path, c, "api")["part_count"] == 3
    assert sessions.load_index(tmp_path)["sessions"][folder.name]["members"] == [a, b, c]
    assert len(collect_meeting_files(tmp_path, date(2026, 11, 9), date(2026, 11, 15))) == 1


def test_earlier_part_arrives_late_keeps_stable_output_and_correct_week(tmp_path, monkeypatch, notes):
    start = datetime(2026, 11, 8, 23, 55).astimezone()  # Sunday -> Monday
    b, folder = add_part(tmp_path, "20261109_B", start + timedelta(minutes=7), 600, "后半")
    a, _ = add_part(tmp_path, "20261108_A", start, 300, "前半")
    monkeypatch.setattr(sessions, "judge_continuation", lambda *args: True)
    result = sessions.auto_merge(tmp_path, a, "api")
    assert result["final_dir"] == str(folder)
    assert notes[0].index("前半") < notes[0].index("后半")
    assert len(collect_meeting_files(tmp_path, date(2026, 11, 2), date(2026, 11, 8))) == 1
    assert collect_meeting_files(tmp_path, date(2026, 11, 9), date(2026, 11, 15)) == []


@pytest.mark.parametrize("case", ["unrelated", "long_gap", "overlap", "unknown_time", "empty", "disabled"])
def test_conservative_non_merge(tmp_path, start, monkeypatch, notes, case):
    add_part(tmp_path, "20261110_A", start, 600, "项目甲")
    offset = {"long_gap": 1300, "overlap": 500}.get(case, 700)
    b, _ = add_part(tmp_path, "20261110_B", None if case == "unknown_time" else start + timedelta(seconds=offset),
                    600, "项目乙", valid=case != "empty")
    seen = []
    monkeypatch.setattr(sessions, "judge_continuation", lambda *args: seen.append(args) or case != "unrelated")
    if case == "disabled":
        monkeypatch.setenv("VOICELOOP_SESSION_GAP_MINUTES", "0")
    assert sessions.auto_merge(tmp_path, b, "api") is None
    assert len(sessions.load_index(tmp_path)["sessions"]) == 2
    assert notes == []
    assert bool(seen) == (case == "unrelated")


def test_ambiguous_two_sessions_remain_independent(tmp_path, start, monkeypatch, notes):
    add_part(tmp_path, "20261110_A", start, 600, "前段")
    add_part(tmp_path, "20261110_C", start + timedelta(minutes=24), 600, "后段")
    b, _ = add_part(tmp_path, "20261110_B", start + timedelta(minutes=12), 600, "中段")
    monkeypatch.setattr(sessions, "judge_continuation", lambda *args: True)
    assert sessions.auto_merge(tmp_path, b, "api") is None
    assert len(sessions.load_index(tmp_path)["sessions"]) == 3


def test_merge_failure_does_not_change_notes_membership_or_raw_files(tmp_path, start, monkeypatch, notes):
    _, first = add_part(tmp_path, "20261110_A", start, 600, "前段")
    _, second = add_part(tmp_path, "20261110_B", start + timedelta(minutes=12), 600, "后段")
    before = (tmp_path / sessions.INDEX).read_bytes()
    original = (first / f"{first.name}.md").read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("model offline")

    monkeypatch.setattr("voiceloop.postprocess.run_minutes_for_dir", fail)
    with pytest.raises(RuntimeError, match="model offline"):
        sessions.merge_recordings(tmp_path, [str(first), str(second)], "api", None)
    assert (tmp_path / sessions.INDEX).read_bytes() == before
    assert (first / f"{first.name}.md").read_bytes() == original
    assert (first / sessions.RAW_TRANSCRIPT).read_text() == "前段"
    assert not list(tmp_path.glob("tmp_session_*"))


def test_commit_failure_rolls_back_public_files(tmp_path, start, monkeypatch, notes):
    _, first = add_part(tmp_path, "20261110_A", start, 600, "前段")
    _, second = add_part(tmp_path, "20261110_B", start + timedelta(minutes=12), 600, "后段")
    original = {p: p.read_bytes() for p in first.glob("*.md")}
    before = (tmp_path / sessions.INDEX).read_bytes()
    monkeypatch.setattr(sessions, "save_index", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        sessions.merge_recordings(tmp_path, [str(first), str(second)], "mock", None)
    assert all(p.read_bytes() == content for p, content in original.items())
    assert (tmp_path / sessions.INDEX).read_bytes() == before


def test_lock_recovers_interrupted_publication_before_reading_membership(tmp_path, start):
    _, folder = add_part(tmp_path, "20261110_A", start, 600, "原始内容")
    minutes = folder / f"{folder.name}.md"
    original_minutes = minutes.read_text()
    index = (tmp_path / sessions.INDEX).read_text()
    (tmp_path / sessions.JOURNAL).write_text(json.dumps({
        "files": {str(minutes.relative_to(tmp_path)): original_minutes}, "index": index,
    }))
    minutes.write_text("interrupted merged output")
    (tmp_path / sessions.INDEX).write_text("interrupted index")
    result = sessions.list_sessions(tmp_path)
    assert len(result["sessions"]) == 1
    assert minutes.read_text() == original_minutes
    assert (tmp_path / sessions.INDEX).read_text() == index
    assert not (tmp_path / sessions.JOURNAL).exists()


def test_cloud_archive_split_and_persistent_separation(tmp_path, start, monkeypatch, notes):
    data = tmp_path / "data"
    cloud = tmp_path / "cloud"
    a, first = add_part(data, "20261110_A", start, 600, "前段")
    b, second = add_part(data, "20261110_B", start + timedelta(minutes=12), 600, "后段")
    sessions.sync_session(data, first, cloud)
    sessions.sync_session(data, second, cloud)
    old_second = (cloud / f"{second.name}.md").read_text()
    result = sessions.merge_recordings(data, [first.name, second.name], "mock", cloud)
    assert result["part_count"] == 2
    assert len(list(cloud.glob("*.md"))) == 1
    assert (cloud / ".voiceloop-superseded" / f"{second.name}.md").read_text() == old_second

    split = sessions.split_session(data, first.name, [b], "mock", cloud)
    assert len(split["final_dirs"]) == 2
    assert len(list(cloud.glob("*.md"))) == 2
    assert len(collect_meeting_files(data, date(2026, 11, 9), date(2026, 11, 15))) == 2
    assert "后段" not in (first / f"{first.name}_transcript.md").read_text()
    assert "前段" not in (second / f"{second.name}_transcript.md").read_text()
    monkeypatch.setattr(sessions, "judge_continuation", lambda *args: pytest.fail("split pairs must not be judged again"))
    assert sessions.auto_merge(data, b, "api") is None
    # Manual merge deliberately overrides a remembered split.
    sessions.merge_recordings(data, [first.name, second.name], "mock", None)
    assert sessions.load_index(data)["separated"] == []


def test_split_second_model_failure_preserves_merged_session(tmp_path, start, monkeypatch, notes):
    a, first = add_part(tmp_path, "20261110_A", start, 600, "前段")
    b, second = add_part(tmp_path, "20261110_B", start + timedelta(minutes=12), 600, "后段")
    sessions.merge_recordings(tmp_path, [first.name, second.name], "mock", None)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    index = (tmp_path / sessions.INDEX).read_bytes()
    real_render = sessions._render
    calls = []

    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("second generation failed")
        return real_render(*args)

    monkeypatch.setattr(sessions, "_render", fail_second)
    with pytest.raises(RuntimeError):
        sessions.split_session(tmp_path, first.name, [a], "mock", None)
    assert (tmp_path / sessions.INDEX).read_bytes() == index
    assert all(p.read_bytes() == text for p, text in before.items())


@pytest.mark.parametrize("response,expected", [
    ('{"continuation":true,"confidence":0.95,"reason":"回答前段问题"}', True),
    ('```json\n{"continuation":true,"confidence":0.9,"reason":"承接"}\n```', True),
    ('{"continuation":true,"confidence":0.89,"reason":"大概"}', False),
    ('{"continuation":"true","confidence":1,"reason":"承接"}', False),
    ('{"continuation":true,"confidence":1}', False),
    ('{"continuation":true,"confidence":99,"reason":"承接"}', False),
    ('unparseable', False), ('[]', False),
])
def test_classifier_requires_explicit_high_confidence_evidence(monkeypatch, response, expected):
    monkeypatch.setattr("voiceloop.kimi_client.resolve_chat_config", lambda engine: object())
    monkeypatch.setattr("voiceloop.kimi_client.call_chat_api_with_retry", lambda *args, **kwargs: response)
    assert sessions.judge_continuation("前段", "后段", 120, "api") is expected


def test_classifier_mock_does_not_call_api(monkeypatch):
    monkeypatch.setattr("voiceloop.kimi_client.resolve_chat_config", lambda *args: pytest.fail("no credentials needed"))
    assert sessions.judge_continuation("a", "b", 0, "mock") is False
    assert sessions.judge_continuation("a", "b", 0, "codex") is False


@pytest.mark.parametrize("filename", ["20261110 140000-UUID.m4a", "custom-name.m4a"])
def test_recording_metadata_uses_filename_or_embedded_time_not_mtime(tmp_path, monkeypatch, filename):
    audio = tmp_path / filename
    audio.write_bytes(b"test")
    monkeypatch.setattr(sessions.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(sessions.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({
        "format": {"duration": "3600", "tags": {"creation_time": "2026-11-10T06:00:00Z"}}
    })))
    meta = sessions.recording_metadata(audio)
    assert (datetime.fromisoformat(meta["end"]) - datetime.fromisoformat(meta["start"])).total_seconds() == 3600
    assert datetime.fromisoformat(meta["start"]).year == 2026


def test_unknown_metadata_is_not_guessed_and_config_is_validated(tmp_path, monkeypatch):
    audio = tmp_path / "custom.m4a"
    audio.write_bytes(b"test")
    monkeypatch.setattr(sessions.shutil, "which", lambda name: None)
    assert sessions.recording_metadata(audio)["start"] is None
    for value in ("-1", "nan", "inf", "oops"):
        monkeypatch.setenv("VOICELOOP_SESSION_GAP_MINUTES", value)
        with pytest.raises(ValueError):
            sessions.window_minutes()
    monkeypatch.delenv("VOICELOOP_SESSION_GAP_MINUTES")
    monkeypatch.setattr("voiceloop.kimi_client._load_dotenv", lambda: {"VOICELOOP_SESSION_GAP_MINUTES": "15"})
    assert sessions.window_minutes() == 15


def test_pipeline_duplicate_is_idempotent_and_retry_sync(tmp_path, start, monkeypatch):
    from voiceloop import asr, postprocess
    data = tmp_path / "data"
    cloud = tmp_path / "cloud"
    audio = tmp_path / "20261110 140000-A.m4a"
    audio.write_bytes(b"recording A")
    monkeypatch.setattr(watch, "compress_audio_if_needed", lambda path: path)
    monkeypatch.setattr(sessions, "recording_metadata", lambda path: {
        "source_name": path.name, "start": start.isoformat(), "end": (start + timedelta(minutes=10)).isoformat(),
        "duration": 600,
    })
    monkeypatch.setattr("voiceloop.notify.notify_minutes_ready", lambda **kwargs: None)
    result = watch.process_new_recording(audio, data, "mock", "mock", cloud)
    monkeypatch.setattr(asr, "run_asr_for_file_to_dir", lambda *a, **kw: pytest.fail("duplicate ASR"))
    monkeypatch.setattr(postprocess, "run_minutes_for_dir", lambda *a, **kw: pytest.fail("duplicate minutes"))
    (cloud / f"{Path(result['final_dir']).name}.md").unlink()
    again = watch.process_new_recording(audio, data, "mock", "mock", cloud)
    assert again["status"] == "already_processed"
    assert again["final_dir"] == result["final_dir"]
    assert Path(again["synced_path"]).exists()
    assert len(sessions.load_index(data)["recordings"]) == 1


def test_pipeline_automatic_merge_and_classifier_failure_fallback(tmp_path, start, monkeypatch):
    from voiceloop import asr
    data, cloud = tmp_path / "data", tmp_path / "cloud"
    monkeypatch.setattr(watch, "compress_audio_if_needed", lambda path: path)
    monkeypatch.setattr("voiceloop.notify.notify_minutes_ready", lambda **kwargs: None)
    monkeypatch.setattr(sessions, "recording_metadata", lambda path: {
        "source_name": path.name, "start": (start + timedelta(minutes=int(path.stem) * 12)).isoformat(),
        "end": (start + timedelta(minutes=int(path.stem) * 12 + 10)).isoformat(), "duration": 600,
    })
    monkeypatch.setattr(sessions, "judge_continuation", lambda *args: True)
    results = []
    for number in range(2):
        audio = tmp_path / f"{number}.m4a"
        audio.write_bytes(str(number).encode())
        results.append(watch.process_new_recording(audio, data, "mock", "mock", cloud))
    assert results[1]["merged"] is True
    assert results[1]["final_dir"] == results[0]["final_dir"]
    assert len(list(cloud.glob("*.md"))) == 1
    def fail(*args):
        raise RuntimeError("classifier unavailable")
    monkeypatch.setattr(sessions, "judge_continuation", fail)
    audio = tmp_path / "2.m4a"
    audio.write_bytes(b"2")
    result = watch.process_new_recording(audio, data, "mock", "mock", cloud)
    assert result["merged"] is False
    assert Path(result["synced_path"]).exists()
    assert len(sessions.load_index(data)["sessions"]) == 2


def test_manual_legacy_import_and_cli_roundtrip(tmp_path, monkeypatch):
    data, cloud = tmp_path / "data", tmp_path / "cloud"
    monkeypatch.setattr("voiceloop.notify.notify_minutes_ready", lambda **kwargs: pytest.fail("manual commands must not notify"))
    monkeypatch.setattr(sessions.shutil, "which", lambda name: None)
    for name, text in (("20261110_A", "前段"), ("20261110_B", "后段")):
        folder = data / name
        folder.mkdir(parents=True)
        (folder / f"{name}.m4a").write_bytes(name.encode())
        (folder / "transcript.md").write_text(text)
        (folder / "meeting.md").write_text("旧纪要")
    parser = build_parser()
    common = ["--data-dir", str(data), "--sync-dir", str(cloud)]
    result = run(parser.parse_args(["merge", "20261110_A", "20261110_B", "--minutes-engine", "mock", *common]))
    assert result["part_count"] == 2
    assert Path(result["synced_path"]).parent == cloud
    combined = (data / "20261110_A" / "20261110_A_transcript.md").read_text()
    assert combined.index("前段") < combined.index("后段")
    listing = run(parser.parse_args(["sessions", *common]))
    assert len(listing["sessions"]) == 1
    rid = listing["sessions"][0]["parts"][1]["id"]
    result = run(parser.parse_args(["split", "20261110_A", "--part", rid, "--minutes-engine", "mock", *common]))
    assert len(result["final_dirs"]) == 2


def test_manual_commands_validate_folders_and_parts(tmp_path, start, notes):
    a, folder = add_part(tmp_path, "20261110_A", start, 600, "前段")
    with pytest.raises(ValueError, match="at least two"):
        sessions.merge_recordings(tmp_path, [folder.name, folder.name], "mock", None)
    with pytest.raises(ValueError, match="directly under"):
        sessions.merge_recordings(tmp_path, [str(tmp_path.parent), folder.name], "mock", None)
    with pytest.raises(ValueError, match="each session"):
        sessions.split_session(tmp_path, folder.name, [a], "mock", None)
    with pytest.raises(ValueError, match="exactly one"):
        sessions.split_session(tmp_path, folder.name, ["nonexistent"], "mock", None)
