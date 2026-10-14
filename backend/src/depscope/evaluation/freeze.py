import hashlib
import json
from pathlib import Path

from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class FrozenSuite(Contract):
    digest: str
    question_digest: str
    corpus_digest: str
    config_digest: str
    output_path: str


def freeze_suite(questions, config, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    question_bytes = canonical([q.model_dump(mode="json") for q in questions])
    config_bytes = canonical(config)
    fields = {
        "question_digest": digest(question_bytes),
        "corpus_digest": config["corpus_digest"],
        "config_digest": digest(config_bytes),
        "output_path": str(output.resolve()),
    }
    # Location is operational metadata, not experiment identity.
    identity = digest(canonical({k: v for k, v in fields.items() if k != "output_path"}))
    suite = FrozenSuite(digest=identity, **fields)
    path = output / "suite.json"
    if path.exists():
        previous = FrozenSuite.model_validate_json(path.read_bytes())
        if previous.digest != suite.digest:
            raise DomainError(
                "FROZEN_SUITE_MODIFIED",
                "Create a new version with a change record instead of overwriting frozen questions/configuration",
            )
        previous = previous.model_copy(update={"output_path": str(output.resolve())})
        verify_suite(previous)
        return previous
    (output / "questions.json").write_bytes(question_bytes)
    (output / "config.json").write_bytes(config_bytes)
    path.write_bytes(canonical(suite.model_dump(mode="json")))
    return suite


def verify_suite(suite):
    home = Path(suite.output_path)
    if (
        digest((home / "questions.json").read_bytes()) != suite.question_digest
        or digest((home / "config.json").read_bytes()) != suite.config_digest
    ):
        raise DomainError(
            "FROZEN_SUITE_MODIFIED", "Frozen questions or configuration were modified"
        )
    if (
        digest(
            canonical(
                {
                    "question_digest": suite.question_digest,
                    "corpus_digest": suite.corpus_digest,
                    "config_digest": suite.config_digest,
                }
            )
        )
        != suite.digest
    ):
        raise DomainError("FROZEN_SUITE_MODIFIED", "Frozen suite identity differs")
