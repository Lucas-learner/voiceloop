"""iMessage notifications via the shared macos-notify channel.

Best-effort only: notification failures are logged to stderr and never
interrupt the processing pipeline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_NOTIFY_SCRIPT = "~/projects/tools/macos-notify/send-imessage.sh"


def resolve_notify_to() -> str:
    """Recipient phone/email from VOICELOOP_NOTIFY_TO (env or project .env)."""
    recipient = os.environ.get("VOICELOOP_NOTIFY_TO", "").strip()
    if not recipient:
        from .kimi_client import _load_dotenv

        recipient = _load_dotenv().get("VOICELOOP_NOTIFY_TO", "").strip()
    return recipient


def send_imessage(recipient: str, message: str) -> bool:
    """Send an iMessage through the shared channel script. Returns success."""
    script = Path(os.environ.get("VOICELOOP_NOTIFY_SCRIPT", DEFAULT_NOTIFY_SCRIPT)).expanduser()
    if not script.exists():
        print(f"[Notify] Script not found: {script}", file=sys.stderr)
        return False
    try:
        subprocess.run(
            [str(script), recipient, message],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        print(f"[Notify] iMessage sent to {recipient}", file=sys.stderr)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[Notify] iMessage send failed: {exc}", file=sys.stderr)
        return False


def notify_minutes_ready(topic: str | None, folder_name: str) -> None:
    """Notify that a new meeting-minutes note has been generated.

    No-op when VOICELOOP_NOTIFY_TO is not configured. Never raises.
    """
    try:
        recipient = resolve_notify_to()
        if not recipient:
            return
        subject = topic or folder_name
        send_imessage(recipient, f"✅ VoiceLoop 新纪要已生成\n主题：{subject}\n目录：{folder_name}")
    except Exception as exc:  # noqa: BLE001 - notification must not break the pipeline
        print(f"[Notify] Notification skipped: {exc}", file=sys.stderr)
