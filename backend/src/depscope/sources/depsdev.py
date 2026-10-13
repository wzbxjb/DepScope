from urllib.parse import quote

from depscope.ingest.models import Coordinate


def dependencies_uri(coordinate: Coordinate) -> str:
    return ("https://api.deps.dev/v3/systems/pypi/packages/" + quote(coordinate.name, safe="")
            + "/versions/" + quote(coordinate.raw_version, safe="") + ":dependencies")
