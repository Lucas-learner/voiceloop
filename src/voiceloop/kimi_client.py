"""OpenAI-compatible chat client for Kimi, DeepSeek, and custom providers."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChatConfig:
    api_key: str
    base_url: str
    model: str


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv() -> dict[str, str]:
    env_path = _package_root() / ".env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def default_chat_engine() -> str:
    engine = os.environ.get("VOICELOOP_MINUTES_ENGINE") or _load_dotenv().get("VOICELOOP_MINUTES_ENGINE") or "kimi"
    if engine not in ("kimi", "deepseek", "api"):
        raise ValueError(f"unsupported VOICELOOP_MINUTES_ENGINE: {engine}")
    return engine


def resolve_chat_config(engine: str) -> ChatConfig:
    """Resolve provider-specific credentials and model for a chat engine."""
    env = _load_dotenv()

    def setting(name: str, default: str = "") -> str:
        return os.environ.get(name) or env.get(name) or default

    if engine == "kimi":
        api_key = setting("KIMI_API_KEY")
        if not api_key:
            credentials_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
            if credentials_path.exists():
                try:
                    api_key = str(json.loads(credentials_path.read_text(encoding="utf-8")).get("access_token") or "")
                except (json.JSONDecodeError, OSError, TypeError):
                    pass
        config = ChatConfig(api_key, setting("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"), setting("KIMI_MODEL", "kimi-for-coding"))
        key_name = "KIMI_API_KEY"
    elif engine == "deepseek":
        config = ChatConfig(setting("DEEPSEEK_API_KEY"), setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com"), setting("DEEPSEEK_MODEL", "deepseek-flash"))
        key_name = "DEEPSEEK_API_KEY"
    elif engine == "api":
        config = ChatConfig(setting("VOICELOOP_LLM_API_KEY"), setting("VOICELOOP_LLM_BASE_URL"), setting("VOICELOOP_LLM_MODEL"))
        key_name = "VOICELOOP_LLM_API_KEY"
    else:
        raise ValueError(f"unsupported chat engine: {engine}")

    if not config.api_key:
        raise RuntimeError(f"{engine} requires {key_name} (environment variable or project .env)")
    if not config.base_url or not config.model:
        raise RuntimeError(f"{engine} requires a base URL and model ID")
    if not config.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ValueError("Chat API base URL must use HTTPS (or local HTTP)")
    return config


def call_chat_api(prompt: str, config: ChatConfig, system_message: str = "你是一个工作助手，帮助整理会议纪要。", timeout: int = 600) -> str:
    import httpx

    base = config.base_url.rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {config.api_key}"},
        json={
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("Chat API output was truncated; no minutes were saved")
    content = choice["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Chat API returned empty final content")
    return content


def call_chat_api_with_retry(prompt: str, config: ChatConfig, system_message: str = "你是一个工作助手，帮助整理会议纪要。", timeout: int = 600, max_retries: int = 3) -> str:
    """Retry transient transport, rate-limit, and server failures only."""
    import httpx

    for attempt in range(max_retries):
        try:
            return call_chat_api(prompt, config, system_message=system_message, timeout=timeout)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt + 1 == max_retries:
                raise
            retry_after = exc.response.headers.get("Retry-After") if isinstance(exc, httpx.HTTPStatusError) else None
            delay = min(float(retry_after), 60) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
            time.sleep(delay)
    raise RuntimeError("Unexpected exit from chat API retry loop")
