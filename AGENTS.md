# VoiceLoop - Agent Guide

## Project Overview

VoiceLoop is a macOS tool that watches the Apple Voice Memos directory for new recordings, automatically transcribes them, generates AI-powered meeting minutes, renames files with extracted topics, and compiles weekly reports.

## Architecture

```
Voice Memos Dir (watched)
  -> watchdog detects new .m4a
  -> wait for iCloud download
  -> sync to data/YYYYMMDD/
  -> ASR (mlx/api/mock)
  -> AI minutes (kimi/codex/mock)
  -> rename if default-named
  -> weekly cron (Sundays)
```

## Key Files

| Module | Purpose |
|--------|---------|
| `watch.py` | File system watcher using `watchdog` |
| `sync.py` | Copy/sync audio files to dated folders |
| `asr.py` | Speech-to-text: MLX local or API |
| `postprocess.py` | Generate meeting minutes via AI |
| `rename.py` | Detect default names, rename with topic |
| `weekly.py` | Compile weekly reports from minutes |
| `cron.py` | Weekly cron job management |
| `cli.py` | Command-line interface |

## Environment Variables

- `VOICELOOP_SOURCE_DIR` — Voice Memos source directory
- `VOICELOOP_DATA_DIR` — Data output directory
- `VOICELOOP_REPO_ROOT` — Project root
- `VOICELOOP_ASR_API_URL` — External ASR API endpoint
- `VOICELOOP_ASR_API_KEY` — External ASR API key
- `VOICELOOP_ASR_API_MODEL` — External ASR model name
- `KIMI_API_KEY` — Fallback Kimi API key

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
