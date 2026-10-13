import hashlib
import json
import re

from packageurl import PackageURL

from depscope.ingest.models import Coordinate
from depscope.runtime.errors import DomainError

from .versions import canonical_version


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def identify(name: str, version: str | None, purl: str | None) -> Coordinate | None:
    normalized = normalized_name(name)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", normalized):
        return None
    purl_version = None
    if purl:
        try:
            parsed = PackageURL.from_string(purl)
        except (ValueError, TypeError):
            raise DomainError("PURL_INVALID", "Package URL is invalid") from None
        if parsed.type != "pypi":
            return None
        if parsed.namespace or parsed.subpath or normalized_name(parsed.name) != normalized:
            raise DomainError("COORDINATE_CONFLICT", "Package URL conflicts with component name")
        purl_version = parsed.version
        if version and purl_version:
            lhs, rhs = canonical_version(version), canonical_version(purl_version)
            if lhs != rhs or (lhs is None and version != purl_version):
                raise DomainError("COORDINATE_CONFLICT", "Package URL conflicts with component version")
    raw_version = version or purl_version
    canonical = canonical_version(raw_version)
    if canonical is None:
        return None
    return Coordinate(name=normalized, version=canonical, raw_version=raw_version)


def snapshot_key(project_id: str, source_kind: str, digest: str) -> str:
    payload = json.dumps([project_id, source_kind, digest], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def instance_key(snapshot_id: str, local_id: str) -> str:
    payload = json.dumps([snapshot_id, local_id], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
