import json

import httpx

from app.config import settings
from app.llm.base import AssessmentOutput


class GroqProviderError(RuntimeError):
    pass


class GroqProvider:
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    async def assess(self, case_context: dict[str, object]) -> AssessmentOutput:
        if not settings.groq_api_key:
            raise GroqProviderError("GROQ_API_KEY is not configured")
        system = "Assess only from the provided evidence. Never invent facts. List conflicts explicitly. Return JSON only."
        user = json.dumps(case_context, default=str)[:12000]
        last_error = ""
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            for attempt in range(settings.llm_max_retries + 1):
                prompt = user if not last_error else f"Previous validation error: {last_error}\nReturn corrected JSON only.\n{user}"
                response = await client.post(self.endpoint, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, json={"model": settings.llm_model, "temperature": 0.1, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                try:
                    result = AssessmentOutput.model_validate_json(content)
                    usage = payload.get("usage")
                    if usage:
                        result.token_usage = {key: int(value) for key, value in usage.items() if isinstance(value, int)}
                    return result
                except Exception as error:
                    last_error = str(error)
                    if attempt >= settings.llm_max_retries:
                        raise GroqProviderError(f"Groq returned invalid assessment after retries: {last_error}") from error
        raise GroqProviderError("Groq assessment failed")
