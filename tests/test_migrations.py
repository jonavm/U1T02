from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, Uuid, select

from app.database import Job, make_database, utcnow
from app.migrate import upgrade_database


def test_unversioned_phase2_database_is_adopted_without_data_loss(settings):
    engine, sessions = make_database(settings.database_url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    job_id = uuid4()
    settings.storage_dir.mkdir()
    document = settings.storage_dir / f"{job_id}.txt"
    document.write_text("Keep this original", encoding="utf-8")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            metadata = MetaData()
            jobs = Table("jobs", metadata, autoload_with=connection)
            dispatch = Table("job_dispatches", metadata, autoload_with=connection)
            # SQLite reflects UUID storage as CHAR, so restore its Python conversion.
            jobs.c.id.type = Uuid()
            dispatch.c.job_id.type = Uuid()
            connection.execute(
                jobs.insert().values(
                    id=job_id,
                    original_filename="old.txt",
                    storage_key=document.name,
                    detected_type="text/plain",
                    size_bytes=document.stat().st_size,
                    sha256="a" * 64,
                    ocr_language="eng",
                    status="queued",
                    stage="awaiting_processing",
                    attempts=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            connection.execute(
                dispatch.insert().values(job_id=job_id, status="pending", available_at=utcnow())
            )
            # Reproduce the unversioned phase 2 schema inside this isolated test database.
            Table("alembic_version", metadata, autoload_with=connection).drop(connection)
        upgrade_database(engine)
        upgrade_database(engine)
        with sessions() as session:
            job = session.get(Job, job_id)
            assert job.original_filename == "old.txt"
            assert job.status == "queued" and job.ocr_mode == "auto"
            assert session.scalar(select(dispatch.c.status)) == "pending"
        assert document.read_text() == "Keep this original"
    finally:
        engine.dispose()
