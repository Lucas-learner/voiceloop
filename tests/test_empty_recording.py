from pathlib import Path

from voiceloop.postprocess import parse_kimi_response, parse_valid_flag
from voiceloop import watch


def test_parse_valid_flag_explicit_no():
    response = "=== FILE: meeting.md ===\n内容\n=== END FILE ===\n=== TOPIC: 某会议 ===\n=== VALID: no ==="
    _, topic = parse_kimi_response(response)
    assert parse_valid_flag(response, topic) is False


def test_parse_valid_flag_explicit_yes():
    response = "=== TOPIC: 项目讨论 ===\n=== VALID: yes ==="
    _, topic = parse_kimi_response(response)
    assert parse_valid_flag(response, topic) is True


def test_parse_valid_flag_keyword_fallback():
    assert parse_valid_flag("no flag here", "空白录音无有效内容") is False
    assert parse_valid_flag("no flag here", "录音开始无实质内容") is False


def test_parse_valid_flag_defaults_true():
    assert parse_valid_flag("no flag here", "季度产品规划会议") is True
    assert parse_valid_flag("no flag here", None) is True


def _make_recording(tmp_path: Path) -> Path:
    audio = tmp_path / "20261024 120000-ABCDEF12.m4a"
    audio.write_bytes(b"fake audio")
    return audio


def _patch_pipeline(monkeypatch, tmp_path: Path, minutes_result: dict):
    monkeypatch.setattr(watch, "compress_audio_if_needed", lambda p: p)
    monkeypatch.setattr(
        "voiceloop.asr.run_asr_for_file_to_dir",
        lambda audio_path, output_dir, engine="mlx": [{"speaker": "", "content": "text"}],
    )
    monkeypatch.setattr(
        "voiceloop.postprocess.run_minutes_for_dir",
        lambda input_dir, engine="kimi": minutes_result,
    )
    calls = {"sync": 0, "notify": 0}

    class _Sync:
        @staticmethod
        def recording_day(path):
            return "20261024"

        @staticmethod
        def recording_timestamp(path):
            from datetime import datetime

            return datetime(2026, 10, 24, 12, 0, 0)

        @staticmethod
        def sync_minutes_to_cloud(final_dir, sync_dir):
            calls["sync"] += 1
            return sync_dir / f"{final_dir.name}.md" if sync_dir else None

    class _Notify:
        @staticmethod
        def notify_minutes_ready(topic, folder_name):
            calls["notify"] += 1

    import sys
    import types
    import voiceloop.sync as real_sync
    import voiceloop.rename as real_rename

    fake_sync = types.ModuleType("voiceloop.sync")
    fake_sync.recording_day = _Sync.recording_day
    fake_sync.recording_timestamp = _Sync.recording_timestamp
    fake_sync.sync_minutes_to_cloud = _Sync.sync_minutes_to_cloud
    fake_notify = types.ModuleType("voiceloop.notify")
    fake_notify.notify_minutes_ready = _Notify.notify_minutes_ready

    monkeypatch.setitem(sys.modules, "voiceloop.sync", fake_sync)
    monkeypatch.setitem(sys.modules, "voiceloop.notify", fake_notify)
    return calls


def test_process_new_recording_syncs_valid_content(monkeypatch, tmp_path: Path):
    audio = _make_recording(tmp_path)
    data_dir = tmp_path / "data"
    calls = _patch_pipeline(monkeypatch, tmp_path, {"topic": "真实会议", "has_content": True})

    result = watch.process_new_recording(audio, data_dir, asr_engine="mock", minutes_engine="mock")

    assert calls["sync"] == 1
    assert calls["notify"] == 1
    assert result["has_content"] is True


def test_process_new_recording_skips_sync_for_empty(monkeypatch, tmp_path: Path):
    audio = _make_recording(tmp_path)
    data_dir = tmp_path / "data"
    calls = _patch_pipeline(monkeypatch, tmp_path, {"topic": "空白录音无有效内容", "has_content": False})

    result = watch.process_new_recording(audio, data_dir, asr_engine="mock", minutes_engine="mock")

    assert calls["sync"] == 0
    assert calls["notify"] == 0
    assert result["has_content"] is False
    assert result["synced_path"] is None
    # Local folder is still kept
    assert Path(result["final_dir"]).exists()
