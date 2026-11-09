import httpx

from app.adapters.paypal_real import PayPalAuthError, auth_hint
from app.config import Settings
from app.llm.groq_provider import SYSTEM_PROMPT
from app.services.pipeline import _transient

TOKEN_URL = "https://api-m.sandbox.paypal.com/v1/oauth2/token"


def _response(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", TOKEN_URL))


def test_invalid_client_hint_names_the_likely_cause():
    message = auth_hint(_response(401, {"error": "invalid_client", "error_description": "Client Authentication failed"}))
    assert "invalid_client" in message
    assert "Client Authentication failed" in message
    assert "SANDBOX" in message


def test_auth_hint_survives_a_non_json_body():
    response = httpx.Response(502, text="Bad gateway", request=httpx.Request("POST", TOKEN_URL))
    assert "HTTP 502" in auth_hint(response)


def test_auth_error_is_not_transient_so_the_pipeline_falls_back_to_the_labeled_mock():
    response = _response(401, {"error": "invalid_client"})
    error = PayPalAuthError(auth_hint(response), request=response.request, response=response)
    assert _transient(error) is False
    assert "invalid_client" in str(error)


def test_auth_server_error_is_still_transient():
    response = _response(503)
    error = PayPalAuthError(auth_hint(response), request=response.request, response=response)
    assert _transient(error) is True


def test_pasted_secrets_are_cleaned_of_spaces_quotes_and_newlines():
    cleaned = Settings(_env_file=None, paypal_client_id='  "abc123"\n', paypal_client_secret="'secret' ", groq_api_key="   ")
    assert cleaned.paypal_client_id == "abc123"
    assert cleaned.paypal_client_secret == "secret"
    assert cleaned.groq_api_key is None


def test_system_prompt_forbids_outside_policy_claims_and_duplicate_conflicts():
    assert "outside policies" in SYSTEM_PROMPT
    assert "ADDITIONAL conflicts" in SYSTEM_PROMPT
