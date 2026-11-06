from decimal import Decimal

import httpx

from app.config import settings
from app import main


class FakePayPal:
    async def create_order(self, amount: Decimal, currency: str = "USD"):
        return {"id": "TEST-ORDER-123", "status": "CREATED", "links": []}

    async def capture_order(self, order_id: str):
        return {"id": order_id, "status": "COMPLETED", "purchase_units": []}


def test_paypal_checkout_disabled_in_mock_mode(client):
    response = client.post("/paypal/orders", json={"amount": 10, "currency": "USD"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SANDBOX_REQUIRED"


def test_paypal_checkout_create_and_capture_sandbox_order(client, monkeypatch):
    monkeypatch.setattr(settings, "paypal_mode", "sandbox")
    monkeypatch.setattr(settings, "paypal_client_id", "public-sandbox-client-id")
    monkeypatch.setattr(main, "get_adapter", lambda: FakePayPal())

    config = client.get("/paypal/config")
    assert config.status_code == 200
    assert config.json() == {"mode": "sandbox", "client_id": "public-sandbox-client-id", "currency": "USD"}

    created = client.post("/paypal/orders", json={"amount": 10, "currency": "USD"})
    assert created.status_code == 200
    assert created.json()["id"] == "TEST-ORDER-123"

    captured = client.post("/paypal/orders/TEST-ORDER-123/capture", json={})
    assert captured.status_code == 200
    assert captured.json()["status"] == "COMPLETED"


def test_paypal_checkout_rejects_invalid_amount(client):
    response = client.post("/paypal/orders", json={"amount": 0, "currency": "USD"})
    assert response.status_code == 422


def test_ai_proxy_sanitizes_client_payload_and_keeps_function_tools(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
    monkeypatch.setattr(settings, "llm_model", "llama-3.3-70b-versatile")
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "I found two urgent disputes.", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "view_schema", "arguments": "{}"}}]}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post("/ai/proxy", json={
        "instructions": "Never expose this as an upstream field",
        "messages": [{"role": "system", "content": "You are an analyst."}, {"role": "user", "content": "Find urgent disputes."}],
        "tools": [{"type": "function", "function": {"name": "view_schema", "description": "Read schema", "parameters": {"type": "object", "properties": {}}}}],
        "tool_choice": "auto", "max_tokens": 999999, "stream": True, "model": "attacker-model",
    })
    assert response.status_code == 200
    import json
    sent = json.loads(calls[0].content)
    assert sent["model"] == "llama-3.3-70b-versatile"
    assert sent["max_completion_tokens"] == 1200 and sent["stream"] is False
    assert "max_tokens" not in sent and "instructions" not in sent
    assert sent["tools"][0]["function"]["name"] == "view_schema"
    assert response.json()["choices"][0]["message"]["tool_calls"]
