"""Explicit project-scoped configuration, with secret-safe representations."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

from .errors import DomainError

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _endpoint(value: str, key: str, schemes: tuple[str, ...]) -> str:
    try:
        url = urlsplit(value)
        port = url.port
        valid = url.scheme in schemes and url.hostname and not url.username and not url.password
        valid = valid and not url.query and not url.fragment
        if port is not None and not 1 <= port <= 65535:
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise DomainError("CONFIG_INVALID", "Invalid service endpoint", (f"/{key}",))
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str | None = None
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = field(default_factory=lambda: SecretStr(""), repr=False)
    deepseek_api_key: SecretStr = field(default_factory=lambda: SecretStr(""), repr=False)
    deepseek_base_url: str = "https://api.deepseek.com"
    generation_model: str = "deepseek-flash"
    embedding_url: str | None = None
    embedding_model: str = "qwen3-embedding:0.6b"
    data_root: Path = PROJECT_ROOT / "data/runtime"
    ai_max_calls: int = 20
    ai_max_amount_usd: Decimal | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        uri = env.get("NEO4J_URI") or None
        if uri:
            uri = _endpoint(uri, "NEO4J_URI", ("bolt", "neo4j", "bolt+s", "neo4j+s"))
        base = _endpoint(env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                         "DEEPSEEK_BASE_URL", ("https", "http"))
        embedding = env.get("OLLAMA_BASE_URL") or None
        if embedding:
            embedding = _endpoint(embedding, "OLLAMA_BASE_URL", ("http", "https"))
        try:
            calls = int(env.get("AI_MAX_CALLS") or "20")
            if calls < 0:
                raise ValueError
        except ValueError:
            raise DomainError("CONFIG_INVALID", "Call limit must be a non-negative integer",
                              ("/AI_MAX_CALLS",)) from None
        amount = None
        if env.get("AI_MAX_AMOUNT_USD"):
            try:
                amount = Decimal(env["AI_MAX_AMOUNT_USD"])
                if not amount.is_finite() or amount < 0:
                    raise InvalidOperation
            except InvalidOperation:
                raise DomainError("CONFIG_INVALID", "Amount must be finite and non-negative",
                                  ("/AI_MAX_AMOUNT_USD",)) from None
        return cls(neo4j_uri=uri, neo4j_user=env.get("NEO4J_USER") or "neo4j",
                   neo4j_password=SecretStr(env.get("NEO4J_PASSWORD", "")),
                   deepseek_api_key=SecretStr(env.get("DEEPSEEK_API_KEY", "")),
                   deepseek_base_url=base,
                   generation_model=env.get("GENERATION_MODEL") or "deepseek-flash",
                   embedding_url=embedding,
                   embedding_model=env.get("EMBEDDING_MODEL") or "qwen3-embedding:0.6b",
                   data_root=Path(env.get("DEPSCOPE_DATA_ROOT") or PROJECT_ROOT / "data/runtime"),
                   ai_max_calls=calls, ai_max_amount_usd=amount)

    def public_summary(self) -> dict:
        return {"database_configured": bool(self.neo4j_uri),
                "generation_configured": bool(self.deepseek_api_key.get_secret_value()),
                "embedding_configured": bool(self.embedding_url),
                "generation_model": self.generation_model,
                "embedding_model": self.embedding_model,
                "ai_max_calls": self.ai_max_calls,
                "ai_max_amount_usd": str(self.ai_max_amount_usd)
                if self.ai_max_amount_usd is not None else None}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    import os

    from dotenv import dotenv_values
    # Read only this project's file; explicitly supplied environment wins.
    values = {key: value for key, value in dotenv_values(PROJECT_ROOT / ".env").items()
              if value is not None}
    values.update(os.environ if env is None else env)
    return Settings.from_env(values)
