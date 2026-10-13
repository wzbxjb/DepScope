from neo4j import GraphDatabase

from depscope.runtime.config import Settings
from depscope.runtime.errors import DomainError


def connect(settings: Settings):
    if not settings.neo4j_uri:
        raise DomainError("DATABASE_NOT_CONFIGURED", "Configure the project-local database")
    return GraphDatabase.driver(settings.neo4j_uri,
                                auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
                                connection_timeout=10, max_connection_pool_size=20)
