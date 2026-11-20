from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Base
from app.errors import AppError
from app.locks import resource_lock
from app.main import create_app


def test_reference_offer_and_campaign_reads_and_request_id(system):
    api, tracker, _ = system
    tracker.campaigns[101]["token"] = "private-click-api-token"
    response = api.get("/api/references", headers={"X-Request-ID": "test_" + uuid4().hex})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("test_")
    assert any(c["code"] == "AU" for c in response.json()["countries"])
    assert len(api.get("/api/offers?q=1112").json()) == 1
    assert api.get("/api/offers?q=not-existing-offer").json() == []
    campaigns = api.get("/api/campaigns")
    assert len(campaigns.json()) == 1
    assert "private-click-api-token" not in campaigns.text
    assert api.get("/api/meta").json()["configured"]
    assert api.get("/live").json()["status"] == "alive"
    assert api.get("/ready").status_code == 200
    assert api.get("/api/operations").json() == []
    assert api.get("/api/operations/missing").status_code == 404
    assert api.post("/api/operations/missing/retry").status_code == 404
    assert (
        api.patch(
            "/api/streams/999/draft", json={"version": 1, "action": "add", "offer_id": 1112}
        ).status_code
        == 404
    )


def test_app_token_authentication_and_unconfigured_readiness(tmp_path):
    application = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'auth.db'}",
            keitaro_api_key="",
            app_access_token="wrapper-token",
            frontend_dir=tmp_path / "absent",
        )
    )
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as api:
        assert api.get("/api/meta").status_code == 401
        result = api.get("/api/meta", headers={"X-App-Token": "wrapper-token"})
        assert result.status_code == 200
        assert not result.json()["configured"]
        assert api.get("/ready").status_code == 503
        assert api.get("/").status_code == 200
        assert api.get("/openapi.json").status_code == 200


def test_database_resource_lock_rejects_overlapping_mutations(system):
    _, _, application = system
    with resource_lock(application.state.sessions, "campaign:101"):
        with pytest.raises(AppError) as error:
            with resource_lock(application.state.sessions, "campaign:101"):
                pytest.fail("Second writer acquired the lock")
        assert error.value.code == "busy"
    with resource_lock(application.state.sessions, "campaign:101"):
        pass
