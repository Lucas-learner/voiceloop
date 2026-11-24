import httpx
import pytest

from voiceloop.kimi_client import ChatConfig, call_chat_api, call_chat_api_with_retry, resolve_chat_config
from voiceloop.cli import build_parser


def test_provider_defaults_and_custom_api(monkeypatch):
    monkeypatch.setattr("voiceloop.kimi_client._load_dotenv", lambda: {})
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICELOOP_LLM_API_KEY", "other-key")
    monkeypatch.setenv("VOICELOOP_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("VOICELOOP_LLM_MODEL", "custom-model")

    kimi = resolve_chat_config("kimi")
    assert kimi.model == "kimi-for-coding"
    assert kimi.base_url == "https://api.kimi.com/coding/v1"
    deepseek = resolve_chat_config("deepseek")
    assert deepseek.model == "deepseek-flash"
    assert deepseek.base_url == "https://api.deepseek.com"
    assert resolve_chat_config("api") == ChatConfig("other-key", "https://example.com/v1", "custom-model")


def test_chat_call_uses_selected_model_and_final_content(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "纪要", "reasoning_content": "internal"}}]}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    assert call_chat_api("转录", ChatConfig("key", "https://api.deepseek.com", "deepseek-flash")) == "纪要"
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    assert sent["json"]["model"] == "deepseek-flash"
    assert sent["headers"]["Authorization"] == "Bearer key"
    assert "User-Agent" not in sent["headers"]


def test_chat_does_not_retry_invalid_model(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        request = httpx.Request("POST", url)
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad model", request=request, response=response)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        call_chat_api_with_retry("prompt", ChatConfig("key", "https://example.com/v1", "bad"))
    assert len(calls) == 1


def test_default_engine_applies_to_watch_and_weekly(monkeypatch):
    monkeypatch.setenv("VOICELOOP_MINUTES_ENGINE", "deepseek")
    parser = build_parser()
    assert parser.parse_args(["watch"]).minutes_engine == "deepseek"
    assert parser.parse_args(["weekly"]).engine == "deepseek"
    assert parser.parse_args(["process-file", "sample.m4a", "--minutes-engine", "api"]).minutes_engine == "api"
