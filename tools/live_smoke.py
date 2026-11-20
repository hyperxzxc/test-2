"""Explicit live integration check. Uses server .env; never prints credentials."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.db import make_session_factory
from app.keitaro import KeitaroClient
from app.models import EditorStream, Operation
from app.schemas import CreateCampaign, DraftAction
from app.services import CampaignService, EditorService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create", action="store_true", help="Allow one idempotent live test campaign"
    )
    parser.add_argument("--domain", type=int)
    parser.add_argument("--group", type=int)
    parser.add_argument("--source", type=int)
    parser.add_argument("--offer", type=int)
    parser.add_argument("--key", default="live-smoke-20261120-v1")
    args = parser.parse_args()
    settings = Settings()
    client = KeitaroClient(settings)
    try:
        refs = client.references()
        print(
            json.dumps(
                {
                    "domains": len(refs["domains"]),
                    "groups": len(refs["groups"]),
                    "sources": len(refs["sources"]),
                    "offers": len(client.offers()),
                }
            )
        )
        if not args.create:
            return
        if not all((args.domain, args.group, args.source, args.offer)):
            parser.error("--create requires --domain --group --source --offer")
        engine, sessions = make_session_factory(settings.database_url)
        try:
            creator = CampaignService(sessions, client)
            payload = CreateCampaign(
                name="test_hyper_adrobot_smoke_20261120",
                country="AU",
                offer_id=args.offer,
                domain_id=args.domain,
                group_id=args.group,
                traffic_source_id=args.source,
            )
            operation = creator.create(payload, args.key)
            print(
                json.dumps(
                    {
                        "operation_id": operation["id"],
                        "status": operation["status"],
                        "campaign_id": operation["campaign_id"],
                        "error": operation["error"],
                    }
                )
            )
            if operation["status"] != "completed":
                raise SystemExit(1)
            replay = creator.create(payload, args.key)
            assert replay["id"] == operation["id"]
            editor = EditorService(sessions, client)
            with sessions() as db:
                rows = db.scalars(
                    select(EditorStream).where(EditorStream.campaign_id == operation["campaign_id"])
                ).all()
                for row in rows:
                    if row.pending_operation_id:
                        pending = db.get(Operation, row.pending_operation_id)
                        recovered = editor.publish(
                            row.stream_id, pending.request["version"], pending.key
                        )
                        assert recovered["status"] == "completed", recovered["error"]
            streams = editor.fetch(operation["campaign_id"])
            offer_stream = next(s for s in streams if s["editable"])
            draft = editor.edit(
                offer_stream["stream_id"],
                DraftAction(version=offer_stream["version"], action="pin", offer_id=args.offer),
            )
            assert draft["dirty"]
            cancelled = editor.cancel(draft["stream_id"], draft["version"])
            assert not cancelled["dirty"]
            draft = editor.edit(
                cancelled["stream_id"],
                DraftAction(version=cancelled["version"], action="pin", offer_id=args.offer),
            )
            published = editor.publish(
                draft["stream_id"], draft["version"], args.key + "-publish-" + str(draft["version"])
            )
            print(json.dumps({"publish_status": published["status"], "error": published["error"]}))
            assert published["status"] == "completed"
            # Restore wrapper-only pin metadata; do not leave a test draft
            current = next(s for s in editor.list(operation["campaign_id"]) if s["editable"])
            draft = editor.edit(
                current["stream_id"],
                DraftAction(version=current["version"], action="unpin", offer_id=args.offer),
            )
            final = editor.publish(
                draft["stream_id"], draft["version"], args.key + "-unpin-" + str(draft["version"])
            )
            assert final["status"] == "completed"
            report = Path("docs/live-verification.md")
            report.parent.mkdir(exist_ok=True)
            report.write_text(
                "# Live verification · 2026-11-20\n\n"
                f"Tracker: {settings.keitaro_base_url}\n\n"
                f"Test campaign ID: {operation['campaign_id']}\n\n"
                "Confirmed: read references; create disabled campaign; configure two streams; "
                "read back configuration; enable; replay without duplicates; Fetch; pin; Cancel; "
                "publish bindings; verify; unpin and publish\n\n"
                "The key can access only one offer. Adding a second distinct offer and "
                "Remove/Bring back were verified on the local simulator "
                "and in integration tests\n\n"
                "Only this tool's own test campaign was modified. Existing campaigns and offers "
                "were not changed or deleted. No credentials are included in this report\n",
                encoding="utf-8",
            )
            print(json.dumps({"verified": True, "campaign_id": operation["campaign_id"]}))
        finally:
            engine.dispose()
    finally:
        client.close()


if __name__ == "__main__":
    main()
