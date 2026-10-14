import httpx

from depscope.runtime.errors import DomainError

from .models import GenerationResult


class DeepSeekGeneration:
    def __init__(self, key, base_url, model, http=None):
        self.key, self.base_url, self.model, self.http = key, base_url.rstrip("/"), model, http

    async def generate(self, messages, max_output):
        if not 1 <= max_output <= 1024 or not messages:
            raise DomainError(
                "GENERATION_LIMIT", "Generation requires messages and 1–1024 output tokens"
            )
        if not self.key.get_secret_value():
            raise DomainError("GENERATION_NOT_CONFIGURED", "Configure a private API key locally")
        if self.http is None:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as http:
                return await self._generate(messages, max_output, http)
        return await self._generate(messages, max_output, self.http)

    async def _generate(self, messages, max_output, http):
        try:
            response = await http.post(
                self.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.key.get_secret_value()},
                json={
                    "model": self.model,
                    "messages": [m.model_dump() for m in messages],
                    "thinking": {"type": "disabled"},
                    "max_tokens": max_output,
                    "temperature": 0,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
            )
            if response.status_code in (401, 403):
                raise DomainError(
                    "GENERATION_AUTH_FAILED",
                    "Model authentication failed; check local configuration",
                )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            if not isinstance(choice["message"]["content"], str) or not isinstance(
                data["model"], str
            ):
                raise ValueError
            usage = data.get("usage")
            return GenerationResult(
                text=choice["message"]["content"],
                model_id=data["model"],
                usage=usage if isinstance(usage, dict) else None,
                request_id=data.get("id") or response.headers.get("x-request-id"),
                finish_reason=choice.get("finish_reason"),
            )
        except httpx.TimeoutException:
            raise DomainError(
                "GENERATION_TIMEOUT", "Generation timed out; usage remains unknown"
            ) from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise DomainError(
                "GENERATION_UNAVAILABLE", "Generation provider failed its response contract"
            ) from None
