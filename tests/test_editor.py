from uuid import uuid4

from conftest import edit, fetch_editor


def publish(api, row, key=None):
    return api.post(
        f"/api/streams/{row['stream_id']}/publish",
        json={"version": row["version"]},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_add_is_draft_cancel_discards_it_and_does_not_touch_keitaro(system):
    api, tracker, _ = system
    row = fetch_editor(api)
    row = edit(api, row, "add", 1112)
    assert row["dirty"]
    assert [b["share"] for b in row["bindings"]] == [25] * 4
    assert len(tracker.streams[1002]["offers"]) == 3
    cancelled = api.post("/api/streams/1002/cancel", json={"version": row["version"]}).json()
    assert not cancelled["dirty"]
    assert len(cancelled["bindings"]) == 3
    assert 1112 in tracker.offers


def test_remove_publish_archive_restore_and_pinned_weights(system):
    api, tracker, _ = system
    row = edit(api, fetch_editor(api), "add", 1112)
    key = str(uuid4())
    operation = publish(api, row, key).json()
    assert operation["status"] == "completed", operation
    assert publish(api, row, key).json()["id"] == operation["id"]
    row = next(s for s in api.get("/api/campaigns/101/streams").json() if s["stream_id"] == 1002)
    row = edit(api, row, "remove", 1112)
    assert publish(api, row).json()["status"] == "completed"
    assert 1112 in tracker.offers
    assert not any(b["offer_id"] == 1112 for b in tracker.streams[1002]["offers"])
    row = fetch_editor(api)
    assert next(b for b in row["bindings"] if b["offer_id"] == 1112)["removed"]
    row = edit(api, row, "set_share", 1111, share=25)
    row = edit(api, row, "restore", 1112)
    assert row["bindings"][0]["share"] == 25
    assert sum(b["share"] for b in row["bindings"]) == 100
    assert not any(call[0] == "DELETE" for call in tracker.calls)


def test_external_removal_is_archived_without_rebalancing(system):
    api, tracker, _ = system
    fetch_editor(api)
    tracker.streams[1002]["offers"] = [
        {"offer_id": 1111, "share": 25, "state": "active"},
        {"offer_id": 3749, "share": 25, "state": "active"},
    ]
    row = fetch_editor(api)
    assert [b["share"] for b in row["bindings"]] == [25, 25, 0]
    assert row["bindings"][-1]["removed"]
    assert not row["dirty"]


def test_fetch_preserves_draft_and_reports_external_conflict(system):
    api, tracker, _ = system
    row = edit(api, fetch_editor(api), "add", 1112)
    assert (
        next(s for s in api.post("/api/campaigns/101/fetch").json() if s["stream_id"] == 1002)[
            "version"
        ]
        == row["version"]
    )
    tracker.streams[1002]["offers"].pop()
    response = api.post("/api/campaigns/101/fetch")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "external_conflict"
    assert len(api.get("/api/campaigns/101/streams").json()[1]["bindings"]) == 4


def test_publish_does_not_overwrite_external_changes(system):
    api, tracker, _ = system
    row = edit(api, fetch_editor(api), "add", 1112)
    tracker.streams[1002]["offers"].pop()
    operation = publish(api, row).json()
    assert operation["status"] == "failed"
    assert "изменён" in operation["error"]
    assert not any(call[0] == "PUT" for call in tracker.calls)


def test_unknown_publication_can_be_reconciled_without_second_put(system):
    api, tracker, _ = system
    row = edit(api, fetch_editor(api), "add", 1112)
    tracker.fail_next[("PUT", "streams/1002")] = "timeout_after"
    operation = publish(api, row).json()
    assert operation["status"] == "unknown"
    assert api.post("/api/campaigns/101/fetch").status_code == 409
    assert api.post("/api/operations/" + operation["id"] + "/retry").json()["status"] == "completed"
    assert len([c for c in tracker.calls if c[0] == "PUT"]) == 1


def test_versions_duplicates_last_offer_and_plain_stream_are_protected(system):
    api, _, _ = system
    row = fetch_editor(api)
    stale = row["version"]
    row = edit(api, row, "remove", 1111)
    assert (
        api.patch(
            "/api/streams/1002/draft", json={"version": stale, "action": "add", "offer_id": 1112}
        ).status_code
        == 409
    )
    row = edit(api, row, "remove", 3749)
    response = api.patch(
        "/api/streams/1002/draft",
        json={"version": row["version"], "action": "remove", "offer_id": 3717},
    )
    assert response.status_code == 400
    assert (
        api.patch(
            "/api/streams/1002/draft",
            json={"version": row["version"], "action": "add", "offer_id": 3717},
        ).status_code
        == 409
    )
    assert (
        api.patch(
            "/api/streams/1001/draft", json={"version": 1, "action": "add", "offer_id": 1112}
        ).status_code
        == 400
    )


def test_failed_get_does_not_archive_valid_bindings(system):
    api, tracker, _ = system
    row = fetch_editor(api)
    tracker.fail_next[("GET", "campaigns/101/streams")] = 403
    assert api.post("/api/campaigns/101/fetch").status_code == 502
    saved = api.get("/api/campaigns/101/streams").json()[1]
    assert saved["bindings"] == row["bindings"]


def test_adopt_remote_resolves_fenced_unknown_publication(system):
    api, tracker, _ = system
    row = edit(api, fetch_editor(api), "add", 1112)
    tracker.fail_next[("PUT", "streams/1002")] = "timeout_after"
    operation = publish(api, row).json()
    response = api.post("/api/streams/1002/adopt-remote", json={"version": row["version"]})
    assert response.status_code == 200
    assert not response.json()["dirty"]
    assert response.json()["pending_operation_id"] is None
    assert api.post("/api/operations/" + operation["id"] + "/retry").status_code == 409
