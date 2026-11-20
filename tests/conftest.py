import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import Base
from app.keitaro import KeitaroClient
from app.main import create_app
from tools.demo_keitaro import DemoTracker


@pytest.fixture
def system(tmp_path):
    tracker = DemoTracker()
    database_url = os.environ.get("TEST_DATABASE_URL")
    admin = None
    schema = "test_" + uuid4().hex
    if database_url:
        admin = create_engine(database_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = str(
            make_url(database_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    settings = Settings(
        database_url=database_url or f"sqlite:///{tmp_path / 'test.db'}",
        keitaro_base_url="http://tracker.local",
        keitaro_api_key="test-secret",
        frontend_dir=tmp_path / "missing",
    )
    remote = KeitaroClient(settings, httpx.MockTransport(tracker.handle))
    app = create_app(settings, remote)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as api:
            yield api, tracker, app
    finally:
        app.state.engine.dispose()
        if admin:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture
def create_payload():
    return {
        "name": "Test Australia",
        "country": "au",
        "offer_id": 1111,
        "domain_id": 1,
        "group_id": 1,
        "traffic_source_id": 1,
    }


def fetch_editor(api):
    response = api.post("/api/campaigns/101/fetch")
    assert response.status_code == 200, response.text
    return next(s for s in response.json() if s["stream_id"] == 1002)


def edit(api, row, action, offer_id, **extra):
    response = api.patch(
        f"/api/streams/{row['stream_id']}/draft",
        json={"version": row["version"], "action": action, "offer_id": offer_id, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()
