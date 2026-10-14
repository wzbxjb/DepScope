from typing import Literal, Protocol

from pydantic import Field

from depscope.ingest.models import Contract


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=100000)


class GenerationResult(Contract):
    text: str
    model_id: str
    usage: dict | None
    request_id: str | None
    finish_reason: str | None = None


class GenerationProvider(Protocol):
    async def generate(
        self, messages: tuple[Message, ...], max_output: int
    ) -> GenerationResult: ...
