from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv() -> dict[str, str]:
    """Parse .env file in project root (if exists)."""
    env_path = _package_root() / ".env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        result[key] = value
    return result


def resolve_kimi_config() -> tuple[str, str]:
    """Resolve Kimi API key and base URL.

    Priority:
      1. Environment variables (KIMI_API_KEY, KIMI_BASE_URL)
      2. Project .env file
      3. ~/.kimi/credentials/kimi-code.json (Kimi CLI login)

    Returns:
        (api_key, base_url)
    """
    # 1. Environment variables
    api_key = os.environ.get("KIMI_API_KEY", "")
    base_url = os.environ.get("KIMI_BASE_URL", "")

    # 2. Project .env file
    if not api_key or not base_url:
        env = _load_dotenv()
        if not api_key:
            api_key = env.get("KIMI_API_KEY", "")
        if not base_url:
            base_url = env.get("KIMI_BASE_URL", "")

    # 3. Kimi CLI credentials (fallback for api_key only)
    if not api_key:
        credentials_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
        if credentials_path.exists():
            try:
                data = json.loads(credentials_path.read_text(encoding="utf-8"))
                token = data.get("access_token")
                if token:
                    api_key = str(token)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

    # Default base URL
    if not base_url:
        base_url = "https://api.kimi.com/coding/v1"

    if not api_key:
        raise RuntimeError(
            "Kimi API key not found. Please configure one of:\n"
            "  1. Set KIMI_API_KEY environment variable\n"
            "  2. Add KIMI_API_KEY to .env file in project root\n"
            "  3. Run 'kimi login' to create ~/.kimi/credentials/kimi-code.json\n"
            "Get your key from: https://platform.kimi.com/"
        )

    return api_key, base_url


def call_kimi_api(
    prompt: str,
    api_key: str,
    base_url: str | None = None,
    system_message: str = "你是一个工作助手，帮助整理会议纪要。",
    timeout: int = 600,
) -> str:
    """Call Kimi API via httpx.

    Supports both OpenAI-compatible and direct endpoints.
    """
    import httpx

    base = base_url or "https://api.kimi.com/coding/v1"
    # Ensure base_url ends with /chat/completions for OpenAI-compatible endpoints
    if base.rstrip("/").endswith("/v1"):
        url = base.rstrip("/") + "/chat/completions"
    else:
        url = base.rstrip("/") + "/chat/completions"

    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "KimiCLI/1.44.0",
        },
        json={
            "model": "kimi-latest",
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    response_json = response.json()
    message = response_json["choices"][0]["message"]
    return message.get("content", "") or message.get("reasoning_content", "") or ""


def call_kimi_api_with_retry(
    prompt: str,
    api_key: str,
    base_url: str | None = None,
    system_message: str = "你是一个工作助手，帮助整理会议纪要。",
    timeout: int = 600,
    max_retries: int = 3,
) -> str:
    """Call Kimi API with exponential backoff retry."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return call_kimi_api(
                prompt,
                api_key,
                base_url=base_url,
                system_message=system_message,
                timeout=timeout,
            )
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Kimi API failed after {max_retries} attempts: {last_error}"
                ) from last_error
    raise RuntimeError("Unexpected exit from retry loop")
