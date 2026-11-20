"""Local, disposable Keitaro protocol simulator. Never used implicitly by the application."""

import json
from copy import deepcopy
from threading import RLock

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DemoTracker:
    def __init__(self):
        self.lock = RLock()
        self.calls: list[tuple[str, str, dict | None]] = []
        self.fail_next: dict[tuple[str, str], int | str] = {}
        self.refs = {
            "domains": [{"id": 1, "name": "demo.tracker.local", "state": "active"}],
            "groups": [{"id": 1, "name": "Тестовые кампании"}],
            "traffic_sources": [{"id": 1, "name": "Demo traffic"}],
        }
        self.offers = {
            identifier: {"id": identifier, "name": name, "state": "active"}
            for identifier, name in [
                (1111, "FitoMishki · Weight Loss · ES"),
                (3749, "Miaflow · Beauty · RO"),
                (3717, "Miaflow · Beauty · PL"),
                (1112, "Orys · Beauty · CL"),
                (5001, "Leadgen · Finance · DE"),
            ]
        }
        self.campaigns = {
            101: {
                "id": 101,
                "name": "Demo · Australia · Leadgen",
                "alias": "demo-au",
                "type": "position",
                "state": "active",
                "domain_id": 1,
                "group_id": "1",
                "traffic_source_id": 1,
            }
        }
        self.streams = {
            1001: {
                "id": 1001,
                "campaign_id": 101,
                "name": "Geo · Google",
                "type": "regular",
                "position": 1,
                "state": "active",
                "schema": "redirect",
                "action_type": "http",
                "action_payload": "https://google.com",
                "offers": [],
                "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
            },
            1002: {
                "id": 1002,
                "campaign_id": 101,
                "name": "Offers · All other visitors",
                "type": "regular",
                "position": 2,
                "state": "active",
                "schema": "landings",
                "action_type": "http",
                "landings": [],
                "filters": [],
                "offers": [
                    {"id": 1, "offer_id": 1111, "share": 34, "state": "active"},
                    {"id": 2, "offer_id": 3749, "share": 33, "state": "active"},
                    {"id": 3, "offer_id": 3717, "share": 33, "state": "active"},
                ],
            },
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            path = request.url.path.removeprefix("/admin_api/v1/")
            method = request.method
            body = json.loads(request.content) if request.content else None
            self.calls.append((method, path, body))
            failure = self.fail_next.pop((method, path), None)
            if isinstance(failure, int):
                return httpx.Response(failure, json={"error": "simulated error"})
            if failure == "timeout_before":
                raise httpx.ReadTimeout("simulated timeout", request=request)
            result, status = self._dispatch(method, path, body, request)
            if failure == "timeout_after":
                raise httpx.ReadTimeout("simulated lost response", request=request)
            return httpx.Response(status, json=deepcopy(result))

    def _dispatch(
        self, method: str, path: str, body: dict | None, request: httpx.Request
    ) -> tuple[object, int]:
        parts = path.split("/")
        if method == "GET" and path in self.refs:
            return self.refs[path], 200
        if method == "GET" and path == "offers":
            return list(self.offers.values()), 200
        if method == "GET" and path == "campaigns":
            offset = int(request.url.params.get("offset", 0))
            limit = int(request.url.params.get("limit", 100))
            return list(self.campaigns.values())[offset : offset + limit], 200
        if method == "POST" and path == "campaigns":
            if any(c["alias"] == body["alias"] for c in self.campaigns.values()):
                return {"error": "duplicate alias"}, 400
            identifier = max(self.campaigns, default=100) + 1
            self.campaigns[identifier] = {**body, "id": identifier}
            return self.campaigns[identifier], 200
        if method == "POST" and path == "streams":
            identifier = max(self.streams, default=1000) + 1
            self.streams[identifier] = {**body, "id": identifier}
            return self.streams[identifier], 200
        if len(parts) >= 2 and parts[1].isdigit():
            identifier = int(parts[1])
            collection = {
                "campaigns": self.campaigns,
                "streams": self.streams,
                "offers": self.offers,
            }.get(parts[0])
            if collection is None or identifier not in collection:
                return {"error": "not found"}, 404
            if method == "GET" and len(parts) == 2:
                return collection[identifier], 200
            if (
                method == "GET"
                and len(parts) == 3
                and parts[0] == "campaigns"
                and parts[2] == "streams"
            ):
                return [s for s in self.streams.values() if s["campaign_id"] == identifier], 200
            if (
                method == "POST"
                and len(parts) == 3
                and parts[0] == "campaigns"
                and parts[2] == "enable"
            ):
                self.campaigns[identifier]["state"] = "active"
                return self.campaigns[identifier], 200
            if method == "PUT" and len(parts) == 2 and parts[0] == "streams":
                self.streams[identifier].update(body)
                if self.streams[identifier].get("action_payload") is None:
                    self.streams[identifier]["action_payload"] = ""
                return self.streams[identifier], 200
        return {"error": "not found"}, 404


tracker = DemoTracker()
app = FastAPI(title="LOCAL DEMO ONLY · Keitaro simulator")


@app.api_route("/admin_api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def endpoint(path: str, request: Request):
    if request.headers.get("Api-Key") != "demo-local-only":
        return JSONResponse(status_code=401, content={"error": "Use demo-local-only"})
    body = await request.body()
    result = tracker.handle(httpx.Request(request.method, str(request.url), content=body))
    return JSONResponse(status_code=result.status_code, content=result.json())
