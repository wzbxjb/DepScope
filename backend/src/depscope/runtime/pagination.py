import base64
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from .errors import DomainError


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[dict, ...]
    next_cursor: str | None
    observed_at: str


def now() -> str:
    return datetime.now(UTC).isoformat()


def encode_cursor(scope: str, last: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([scope,last]).encode()).decode()


def decode_cursor(cursor: str | None, scope: str) -> str:
    if cursor is None:
        return ""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor))
        if not isinstance(decoded,list) or len(decoded) != 2 or decoded[0] != scope or not isinstance(decoded[1],str):
            raise ValueError
        return decoded[1]
    except (ValueError, TypeError, UnicodeDecodeError):
        raise DomainError("INVALID_CURSOR", "Cursor does not match this query context") from None


def page_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        raise DomainError("INVALID_PAGE_LIMIT", "Page limit must be between 1 and 100")
    return value
