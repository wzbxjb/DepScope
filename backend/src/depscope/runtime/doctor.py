"""Readiness probes only: never trigger a paid generation request."""
import asyncio
import json

import httpx
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from .config import Settings, load_settings


async def doctor(settings: Settings) -> dict:
    result = {"generation": {"status": "configured" if
              settings.deepseek_api_key.get_secret_value() else "not_configured", "tested": False},
              "database": {"status": "not_configured"},
              "embedding": {"status": "not_configured"}}
    if settings.neo4j_uri:
        def probe_database():
            with GraphDatabase.driver(settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
                    connection_timeout=5) as driver:
                driver.verify_connectivity()
        try:
            await asyncio.to_thread(probe_database)
            result["database"] = {"status": "ready"}
        except (DriverError, Neo4jError, OSError, ValueError):
            result["database"] = {"status": "unavailable"}
    if settings.embedding_url:
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(settings.embedding_url + "/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                present = any(m.get("name") == settings.embedding_model for m in models)
                result["embedding"] = {"status": "ready" if present else "model_missing"}
        except (httpx.HTTPError, ValueError):
            result["embedding"] = {"status": "unavailable"}
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(doctor(load_settings())), indent=2))
