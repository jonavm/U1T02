from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import Settings
from app.database import make_database


def upgrade_database(engine):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


if __name__ == "__main__":
    settings = Settings.from_env()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    engine, _ = make_database(settings.database_url)
    try:
        upgrade_database(engine)
        print("Database migrations applied.")
    finally:
        engine.dispose()
