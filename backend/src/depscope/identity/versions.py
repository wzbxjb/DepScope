from packaging.version import InvalidVersion, Version


def canonical_version(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        return str(Version(raw))
    except InvalidVersion:
        return None
