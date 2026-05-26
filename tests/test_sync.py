from pathlib import Path

from voiceloop.sync import recording_day, destination_for, sync_single_file


def test_recording_day_from_filename():
    p = Path("20260522 100732-CF347703.m4a")
    assert recording_day(p) == "20260522"


def test_destination_for():
    source = Path("20260522 100732-CF347703.m4a")
    data = Path("/tmp/data")
    dest = destination_for(source, data)
    assert dest.name == "20260522_1007_watch.m4a"
    assert dest.parent.name == "20260522"
