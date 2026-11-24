from pathlib import Path

import pytest

from voiceloop.watch import (
    acquire_watch_lock,
    load_processed_sources,
    mark_processed_source,
)


def test_processed_ledger_roundtrip(tmp_path: Path):
    assert load_processed_sources(tmp_path) == set()

    mark_processed_source(tmp_path, "20260919 171113-98CE8D86.m4a")
    mark_processed_source(tmp_path, "20260919 172039-AE9DBF73.m4a")

    assert load_processed_sources(tmp_path) == {
        "20260919 171113-98CE8D86.m4a",
        "20260919 172039-AE9DBF73.m4a",
    }


def test_acquire_watch_lock_blocks_second_instance(tmp_path: Path):
    fh = acquire_watch_lock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            acquire_watch_lock(tmp_path)
    finally:
        fh.close()

    # Lock is released once the holder closes the handle
    fh2 = acquire_watch_lock(tmp_path)
    fh2.close()
