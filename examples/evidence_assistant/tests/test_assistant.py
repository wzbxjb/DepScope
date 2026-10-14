import json
import pytest
from assistant import ExampleAssistant
from depscope.generation.models import GenerationResult
from depscope.runtime.errors import DomainError


class Model:
    def __init__(self, value):
        self.value = value

    async def generate(self, messages, max_output):
        if isinstance(self.value, Exception):
            raise self.value
        return GenerationResult(
            text=json.dumps(self.value),
            model_id="constructed-model",
            usage=None,
            request_id="constructed",
        )


async def test_example_preserves_evidence_ids():
    model = Model({"body": "Summary", "citations": ["record-a"], "limitations": []})
    answer = await ExampleAssistant(model).summarize(
        {"record-a": "Public advisory text"}
    )
    assert answer.status == "answered" and answer.citations == ("record-a",)
    assert answer.explanation_verified is False


async def test_example_rejects_unsupplied_citations():
    answer = await ExampleAssistant(
        Model({"body": "Summary", "citations": ["missing"], "limitations": []})
    ).summarize({"record-a": "Public advisory text"})
    assert answer.status == "unsupported_output" and answer.body == ""


async def test_example_propagates_service_failure():
    with pytest.raises(DomainError, match="GENERATION_TIMEOUT"):
        await ExampleAssistant(
            Model(DomainError("GENERATION_TIMEOUT", "timeout"))
        ).summarize({"record-a": "Public advisory text"})
