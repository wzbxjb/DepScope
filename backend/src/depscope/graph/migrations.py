from depscope.runtime.config import PROJECT_ROOT


def migrate(driver):
    commands = (PROJECT_ROOT / "migrations/001_core.cypher").read_text().split(";")
    with driver.session() as session:
        for command in commands:
            if command.strip():
                session.run(command).consume()
