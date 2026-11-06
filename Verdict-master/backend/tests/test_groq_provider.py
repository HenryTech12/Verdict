import httpx
import pytest

from app.config import settings
from app.llm import groq_provider
from app.llm.groq_provider import GroqProvider, GroqProviderError, extract_json

GOOD = '{"evidence_items":[{"type":"Shipment delivery proof","present":true,"strength":0.9,"note":"ok"}],"conflicts":[],"win_likelihood":0.9,"confidence":0.85,"recommended":"FIGHT","rationale":"Delivered.","packet_draft":"Shipped."}'


def test_extract_json_handles_fences_and_prose():
    assert extract_json("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert extract_json('Here you go: {"a": {"b": 2}} done') == '{"a": {"b": 2}}'
    with pytest.raises(ValueError):
        extract_json("no json here")


def install(monkeypatch, responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    real = httpx.AsyncClient
    monkeypatch.setattr(groq_provider.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setattr(settings, "llm_model", "openai/gpt-oss-120b")
    return calls


def ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 10}})


async def test_request_is_sized_for_reasoning_models(monkeypatch):
    calls = install(monkeypatch, [ok(GOOD)])
    result = await GroqProvider().assess({"checks": {}})
    import json

    body = json.loads(calls[0].content)
    assert body["reasoning_effort"] == "low" and body["max_completion_tokens"] == 4096 and "response_format" not in body
    assert result.recommended == "FIGHT" and result.token_usage == {"total_tokens": 10}


async def test_json_failure_from_groq_is_retried(monkeypatch):
    bad = httpx.Response(400, json={"error": {"code": "json_validate_failed", "failed_generation": "{\"evidence_items\":["}})
    calls = install(monkeypatch, [bad, ok("```json\n" + GOOD + "\n```")])
    assert (await GroqProvider().assess({})).win_likelihood == 0.9
    assert len(calls) == 2


async def test_bad_model_name_fails_fast_with_groqs_message(monkeypatch):
    calls = install(monkeypatch, [httpx.Response(404, json={"error": {"code": "model_not_found"}})])
    with pytest.raises(GroqProviderError, match="model_not_found"):
        await GroqProvider().assess({})
    assert len(calls) == 1
