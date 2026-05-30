# VoiceLoop - Agent Guide

## Project Overview

VoiceLoop is a macOS tool that watches the Apple Voice Memos directory for new recordings, automatically transcribes them, generates AI-powered dialogue notes (meeting minutes, due diligence interviews, roadshows, etc.), compresses large audio files, renames files with extracted topics, syncs notes to iCloud, and compiles weekly reports.

## Architecture

```
Voice Memos Dir (watched)
  -> watchdog detects new .m4a/.qta
  -> wait for iCloud download
  -> copy to data/tmp_YYYYMMDD_HHMMSS/
  -> compress audio if high bitrate (ffmpeg)
  -> ASR (mlx/api/mock) → transcript.md
  -> AI notes (kimi/codex/mock) → meeting.md + topic
  -> rename temp folder → data/YYYYMMDD_主题/
  -> rename files inside to match folder name
  -> sync meeting.md to iCloud
  -> weekly cron (configurable day, default Friday)
```

## Key Files

| Module | Purpose |
|--------|---------|
| `watch.py` | File system watcher using `watchdog`; audio compression; iCloud sync trigger |
| `sync.py` | Copy/sync audio files; iCloud sync utilities |
| `asr.py` | Speech-to-text: MLX local or API; outputs Markdown transcripts |
| `postprocess.py` | Generate dialogue notes via AI; supports generic adaptive prompts |
| `rename.py` | Detect default names, rename with topic |
| `weekly.py` | Compile weekly reports from notes |
| `cron.py` | Weekly cron job management with configurable day-of-week |
| `config.py` | Configuration loading (paths, sync_dir, env vars) |
| `cli.py` | Command-line interface |
| `kimi_client.py` | Kimi API client with retry logic |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VOICELOOP_SOURCE_DIR` | Voice Memos source directory | `~/Library/Group Containers/.../Recordings/` |
| `VOICELOOP_DATA_DIR` | Data output directory | `./data` |
| `VOICELOOP_SYNC_DIR` | iCloud sync directory for notes | `~/Library/Mobile Documents/com~apple~CloudDocs/数据同步/voiceloop` |
| `VOICELOOP_REPO_ROOT` | Project root | package root |
| `VOICELOOP_ASR_API_URL` | External ASR API endpoint | — |
| `VOICELOOP_ASR_API_KEY` | External ASR API key | — |
| `VOICELOOP_ASR_API_MODEL` | External ASR model name | — |
| `KIMI_API_KEY` | Fallback Kimi API key | — |

## Prompt Templates

| File | Purpose | Notes |
|------|---------|-------|
| `prompts/meeting_minutes.md` | Dialogue notes template | Generic adaptive: AI selects relevant sections based on content type (meeting, DD interview, roadshow, etc.) |
| `prompts/weekly.md` | Weekly report template | De-scened to work with any dialogue type |

## Audio Compression

`watch.py:compress_audio_if_needed()` uses `ffprobe` to detect bitrate and `ffmpeg` to transcode to 64 kbps mono AAC when bitrate exceeds 128 kbps. This handles Voice Memos "Lossless" recordings without affecting already-compressed ones.

## Transcript Format

Transcripts are written as **Markdown** (`.md`) instead of CSV. The `speaker` column was always empty (no diarization), so CSV structure offered no benefit. Markdown is human-friendly and LLM-friendly.

Legacy `.csv` transcripts are still readable via backward compatibility in `postprocess.py:read_transcript()`.

## Testing

```bash
# Run all tests
pytest

# Test with mock engine
python -m voiceloop process-file examples/sample_audio/sample.m4a --asr-engine mock --minutes-engine mock
```

## Common Tasks

- Add new ASR engine: extend `asr.py` with `run_<name>_asr()`
- Add new minutes engine: extend `postprocess.py` with `run_<name>_minutes()`
- Modify prompt templates: edit files in `prompts/`
- Adjust audio compression threshold: edit `compress_audio_if_needed()` in `watch.py`
- Change default sync directory: set `VOICELOOP_SYNC_DIR` env var
