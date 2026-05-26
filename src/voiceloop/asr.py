from __future__ import annotations

import csv
import importlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, cast


QWEN_ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"

# Thread-safe lock for appending to transcript CSV
_transcript_lock = threading.Lock()


def day_dir(data_dir: Path, day: str) -> Path:
    return data_dir / day


def transcript_path(data_dir: Path, day: str) -> Path:
    return day_dir(data_dir, day) / f"transcript_{day}.csv"


def audio_files_for_day(data_dir: Path, day: str) -> list[Path]:
    directory = day_dir(data_dir, day)
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.m4a") if path.is_file())


def write_transcript(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["speaker", "content"], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({"speaker": row.get("speaker", ""), "content": row.get("content", "")})


def append_transcript(rows: list[dict[str, str]], output: Path) -> None:
    """Thread-safe append to transcript CSV."""
    with _transcript_lock:
        output.parent.mkdir(parents=True, exist_ok=True)
        file_exists = output.exists()
        with output.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["speaker", "content"], extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for row in rows:
                writer.writerow({"speaker": row.get("speaker", ""), "content": row.get("content", "")})


def run_mock_asr(data_dir: Path, day: str, mock_text: str | None = None) -> dict[str, object]:
    files = audio_files_for_day(data_dir, day)
    rows = [
        {"speaker": "", "content": mock_text or f"Mock transcript for {path.name}."}
        for path in files
    ]
    output = transcript_path(data_dir, day)
    write_transcript(rows, output)
    return {"command": "asr", "engine": "mock", "day": day, "audio_count": len(files), "output_path": str(output), "output_dir": str(output.parent)}


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def run_mlx_asr(data_dir: Path, day: str) -> dict[str, object]:
    try:
        mlx_qwen3_asr = importlib.import_module("mlx_qwen3_asr")
    except ImportError as exc:
        raise RuntimeError("mlx engine requires mlx-qwen3-asr to be installed in this environment") from exc

    rows: list[dict[str, str]] = []
    files = audio_files_for_day(data_dir, day)
    total_files = len(files)
    skipped_files = 0

    output = transcript_path(data_dir, day)
    if output.exists() and files:
        transcript_mtime = output.stat().st_mtime
        all_older = all(path.stat().st_mtime <= transcript_mtime for path in files)
        if all_older:
            print(f"[ASR] Skipping: transcript exists and all audio files are older", file=sys.stderr)
            return {
                "command": "asr",
                "engine": "mlx",
                "model": QWEN_ASR_MODEL,
                "day": day,
                "audio_count": total_files,
                "skipped": total_files,
                "row_count": 0,
                "output_path": str(output),
                "output_dir": str(output.parent),
                "user_note": "Skipped: transcript already exists and is newer than all audio files.",
            }

    for idx, path in enumerate(files, 1):
        if output.exists() and path.stat().st_mtime <= output.stat().st_mtime:
            print(f"[ASR] Skipping {idx}/{total_files}: {path.name} (older than existing transcript)", file=sys.stderr)
            skipped_files += 1
            continue

        print(f"[ASR] Processing {idx}/{total_files}: {path.name}", file=sys.stderr)
        transcribe = cast(Any, mlx_qwen3_asr).transcribe
        result = transcribe(
            str(path),
            model=QWEN_ASR_MODEL,
            verbose=False,
            return_timestamps=False,
            return_chunks=True,
        )
        chunks = cast(list[dict[str, object]], getattr(result, "chunks", None) or [])
        chunk_count = len(chunks)
        for chunk_idx, chunk in enumerate(chunks, 1):
            text = str(chunk.get("text", "")).strip()
            if text:
                rows.append({"speaker": "", "content": text})
            if chunk_count > 20 and chunk_idx % 20 == 0:
                print(f"[ASR]   {path.name}: {chunk_idx}/{chunk_count} chunks...", file=sys.stderr)
        print(f"[ASR] Completed {path.name}: {chunk_count} chunks, {len(rows)} total rows", file=sys.stderr)

    write_transcript(rows, output)
    return {
        "command": "asr",
        "engine": "mlx",
        "model": QWEN_ASR_MODEL,
        "day": day,
        "audio_count": total_files,
        "skipped": skipped_files,
        "row_count": len(rows),
        "output_path": str(output),
        "output_dir": str(output.parent),
        "user_note": "The first real transcription can take a little while because the local speech model may need to download or warm up.",
    }


def run_api_asr(audio_path: Path) -> str:
    """Call an external ASR API (e.g. Whisper) for a single file.

    Configured via environment variables:
        VOICELOOP_ASR_API_URL - API endpoint (default: https://api.openai.com/v1/audio/transcriptions)
        VOICELOOP_ASR_API_KEY - API key
        VOICELOOP_ASR_API_MODEL - Model name (default: whisper-1)
    """
    import httpx

    api_url = os.environ.get("VOICELOOP_ASR_API_URL", "https://api.openai.com/v1/audio/transcriptions")
    api_key = os.environ.get("VOICELOOP_ASR_API_KEY")
    model = os.environ.get("VOICELOOP_ASR_API_MODEL", "whisper-1")

    if not api_key:
        raise RuntimeError(
            "API ASR requires VOICELOOP_ASR_API_KEY environment variable. "
            "Set it to your OpenAI-compatible API key."
        )

    with audio_path.open("rb") as f:
        files = {"file": (audio_path.name, f, "audio/m4a")}
        data = {"model": model, "response_format": "text"}

        response = httpx.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files,
            timeout=120,
        )
        response.raise_for_status()
        return response.text


def run_mlx_asr_for_file(audio_path: Path) -> list[dict[str, str]]:
    """Transcribe a single file with MLX, return rows."""
    try:
        mlx_qwen3_asr = importlib.import_module("mlx_qwen3_asr")
    except ImportError as exc:
        raise RuntimeError("mlx engine requires mlx-qwen3-asr") from exc

    transcribe = cast(Any, mlx_qwen3_asr).transcribe
    result = transcribe(
        str(audio_path),
        model=QWEN_ASR_MODEL,
        verbose=False,
        return_timestamps=False,
        return_chunks=True,
    )
    chunks = cast(list[dict[str, object]], getattr(result, "chunks", None) or [])
    rows = []
    for chunk in chunks:
        text = str(chunk.get("text", "")).strip()
        if text:
            rows.append({"speaker": "", "content": text})
    return rows


def run_asr_for_file(audio_path: Path, data_dir: Path, day: str, engine: str = "mlx") -> list[dict[str, str]]:
    """Transcribe a single file and return transcript rows.

    Also appends to the day's transcript CSV.
    """
    output = transcript_path(data_dir, day)

    if engine == "mock":
        rows = [{"speaker": "", "content": f"Mock transcript for {audio_path.name}."}]
    elif engine == "api":
        text = run_api_asr(audio_path)
        rows = [{"speaker": "", "content": text}]
    elif engine == "mlx":
        rows = run_mlx_asr_for_file(audio_path)
    else:
        raise ValueError(f"unsupported ASR engine: {engine}")

    append_transcript(rows, output)
    return rows


def run_asr(data_dir: Path, day: str, engine: str = "mock", mock_text: str | None = None) -> dict[str, object]:
    if engine == "mock":
        return run_mock_asr(data_dir, day, mock_text=mock_text)
    if engine == "mlx":
        return run_mlx_asr(data_dir, day)
    raise ValueError(f"unsupported ASR engine for batch: {engine}. Use 'mlx' or 'mock'.")


def dumps_summary(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
