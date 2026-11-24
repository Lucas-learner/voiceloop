import sys
from types import SimpleNamespace

import pytest

from voiceloop.asr import run_asr_for_file_to_dir


def test_truncated_asr_does_not_write_transcript(tmp_path, monkeypatch):
    audio = tmp_path / "sample.m4a"
    audio.write_bytes(b"sample")
    monkeypatch.setitem(
        sys.modules,
        "mlx_qwen3_asr",
        SimpleNamespace(transcribe=lambda *args, **kwargs: SimpleNamespace(
            truncated=True,
            chunks=[{"text": "incomplete"}],
        )),
    )

    with pytest.raises(RuntimeError, match="truncated"):
        run_asr_for_file_to_dir(audio, tmp_path)
    assert not (tmp_path / "transcript.md").exists()
