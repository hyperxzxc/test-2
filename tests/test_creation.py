from uuid import uuid4


def create(api, payload, key=None):
    return api.post(
        "/api/campaigns", json=payload, headers={"Idempotency-Key": key or str(uuid4())}
    )


def test_creates_correct_campaign_and_replays_without_duplicates(system, create_payload):
    api, tracker, _ = system
    key = str(uuid4())
    response = create(api, create_payload, key)
    assert response.status_code == 200, response.text
    operation = response.json()
    assert operation["status"] == "completed", operation
    campaign = tracker.campaigns[operation["campaign_id"]]
    assert campaign["state"] == "active"
    assert campaign["type"] == "position"
    streams = [s for s in tracker.streams.values() if s["campaign_id"] == campaign["id"]]
    assert len(streams) == 2
    assert streams[0]["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU"]}]
    assert streams[0]["action_payload"] == "https://google.com"
    assert streams[1]["offers"] == [{"offer_id": 1111, "share": 100, "state": "active"}]
    assert create(api, create_payload, key).json()["id"] == operation["id"]
    assert len(tracker.campaigns) == 2
    assert len(tracker.streams) == 4
    assert len(operation["steps"]) == 4


def test_same_key_with_different_body_is_conflict(system, create_payload):
    api, _, _ = system
    key = str(uuid4())
    create(api, create_payload, key)
    response = create(api, {**create_payload, "name": "Another"}, key)
    assert response.status_code == 409


def test_partial_failure_keeps_campaign_disabled_and_retry_resumes(system, create_payload):
    api, tracker, _ = system
    tracker.fail_next[("POST", "streams")] = 400
    operation = create(api, create_payload).json()
    assert operation["status"] == "failed"
    assert tracker.campaigns[operation["campaign_id"]]["state"] == "disabled"
    result = api.post(f"/api/operations/{operation['id']}/retry").json()
    assert result["status"] == "completed", result
    assert len(tracker.campaigns) == 2
    assert len(tracker.streams) == 4


def test_lost_campaign_response_is_reconciled_by_marker(system, create_payload):
    api, tracker, _ = system
    tracker.fail_next[("POST", "campaigns")] = "timeout_after"
    operation = create(api, create_payload).json()
    assert operation["status"] == "unknown"
    result = api.post(f"/api/operations/{operation['id']}/retry").json()
    assert result["status"] == "completed", result
    assert len([c for c in tracker.calls if c[0] == "POST" and c[1] == "campaigns"]) == 1


def test_unknown_write_without_remote_result_is_not_blindly_retried(system, create_payload):
    api, tracker, _ = system
    tracker.fail_next[("POST", "campaigns")] = "timeout_before"
    operation = create(api, create_payload).json()
    result = api.post(f"/api/operations/{operation['id']}/retry").json()
    assert result["status"] == "unknown"
    assert len([c for c in tracker.calls if c[0] == "POST" and c[1] == "campaigns"]) == 1


def test_lost_stream_response_is_reconciled_without_duplicate(system, create_payload):
    api, tracker, _ = system
    tracker.fail_next[("POST", "streams")] = "timeout_after"
    operation = create(api, create_payload).json()
    assert operation["status"] == "unknown"
    result = api.post(f"/api/operations/{operation['id']}/retry").json()
    assert result["status"] == "completed", result
    assert len(tracker.streams) == 4


def test_invalid_inputs_and_references_do_not_write(system, create_payload):
    api, tracker, _ = system
    assert create(api, {**create_payload, "country": "XX"}).status_code == 422
    assert create(api, {**create_payload, "name": "  "}).status_code == 422
    operation = create(api, {**create_payload, "domain_id": 999}).json()
    assert operation["status"] == "failed"
    operation = create(api, {**create_payload, "offer_id": 999}).json()
    assert operation["status"] == "failed"
    assert not any(call[0] == "POST" for call in tracker.calls)
