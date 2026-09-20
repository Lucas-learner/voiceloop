import subprocess

from voiceloop import notify


def test_resolve_notify_to_from_env(monkeypatch):
    monkeypatch.setenv("VOICELOOP_NOTIFY_TO", "+8613800000000")
    assert notify.resolve_notify_to() == "+8613800000000"


def test_resolve_notify_to_empty(monkeypatch):
    monkeypatch.delenv("VOICELOOP_NOTIFY_TO", raising=False)
    monkeypatch.setattr("voiceloop.kimi_client._load_dotenv", lambda: {})
    assert notify.resolve_notify_to() == ""


def test_send_imessage_missing_script(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICELOOP_NOTIFY_SCRIPT", str(tmp_path / "nope.sh"))
    assert notify.send_imessage("+8613800000000", "hello") is False


def test_send_imessage_success(monkeypatch, tmp_path):
    script = tmp_path / "send.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setenv("VOICELOOP_NOTIFY_SCRIPT", str(script))
    assert notify.send_imessage("+8613800000000", "hello") is True


def test_send_imessage_failure_returns_false(monkeypatch, tmp_path):
    script = tmp_path / "send.sh"
    script.write_text("#!/bin/bash\nexit 1\n")
    script.chmod(0o755)
    monkeypatch.setenv("VOICELOOP_NOTIFY_SCRIPT", str(script))
    assert notify.send_imessage("+8613800000000", "hello") is False


def test_notify_minutes_ready_no_recipient_is_noop(monkeypatch):
    monkeypatch.setattr(notify, "resolve_notify_to", lambda: "")
    calls = []
    monkeypatch.setattr(notify, "send_imessage", lambda *a: calls.append(a))
    notify.notify_minutes_ready(topic="测试主题", folder_name="20260920_测试主题")
    assert calls == []


def test_notify_minutes_ready_sends(monkeypatch):
    monkeypatch.setattr(notify, "resolve_notify_to", lambda: "+8613800000000")
    calls = []
    monkeypatch.setattr(notify, "send_imessage", lambda *a: calls.append(a) or True)
    notify.notify_minutes_ready(topic="测试主题", folder_name="20260920_测试主题")
    assert len(calls) == 1
    recipient, message = calls[0]
    assert recipient == "+8613800000000"
    assert "测试主题" in message


def test_notify_minutes_ready_never_raises(monkeypatch):
    def boom(*a):
        raise subprocess.CalledProcessError(1, "send.sh")

    monkeypatch.setattr(notify, "resolve_notify_to", lambda: "+8613800000000")
    monkeypatch.setattr(notify, "send_imessage", boom)
    notify.notify_minutes_ready(topic=None, folder_name="20260920_x")  # must not raise
