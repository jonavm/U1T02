import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    database_url = os.environ.get("TEST_DATABASE_URL")
    admin_engine = None
    schema = "test_" + uuid4().hex
    if database_url:
        if make_url(database_url).get_backend_name() != "postgresql":
            raise ValueError(
                "TEST_DATABASE_URL must refer to a dedicated PostgreSQL test database."
            )
        admin_engine = create_engine(database_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = (
            make_url(database_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    else:
        database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    try:
        yield Settings(database_url, tmp_path / "documents", max_upload_bytes=1024)
    finally:
        if admin_engine:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()


@pytest.fixture
def api(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app
