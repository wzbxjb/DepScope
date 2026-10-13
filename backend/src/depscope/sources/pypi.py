from datetime import UTC, datetime

from packaging.version import InvalidVersion, Version

from depscope.identity.coordinates import normalized_name
from depscope.runtime.errors import DomainError


def package_uri(name: str) -> str:
    import re
    normalized = normalized_name(name)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", normalized):
        raise DomainError("INVALID_PACKAGE", "Invalid PyPI package name")
    return "https://pypi.org/pypi/" + normalized + "/json"


def select_versions(metadata: dict, cutoff: datetime) -> tuple[str, ...]:
    if cutoff.tzinfo is None:
        raise DomainError("INVALID_CUTOFF", "Version selection cutoff must have a timezone")
    releases = []
    for name, files in metadata.get("releases", {}).items():
        try:
            version = Version(name)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease:
            continue
        timestamps = []
        for file in files:
            if file.get("yanked", False):
                continue
            try:
                uploaded = datetime.fromisoformat(file["upload_time_iso_8601"])
            except (KeyError, ValueError, TypeError):
                continue
            if uploaded.tzinfo is not None and uploaded <= cutoff:
                timestamps.append(uploaded.astimezone(UTC))
        if timestamps:
            releases.append((name, version, min(timestamps)))
    if not releases:
        return ()
    picks = [max(releases, key=lambda row: (row[1], row[0]))[0]]
    for year in (2024, 2025):
        candidates = [row for row in releases if row[2].year == year]
        if candidates:
            picks.append(min(candidates, key=lambda row: (row[2], row[1], row[0]))[0])
    return tuple(dict.fromkeys(picks))
