from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain import digest, offer_payload, rebalance, stream_fingerprint
from app.errors import AppError, KeitaroError
from app.keitaro import KeitaroClient
from app.locks import resource_lock
from app.models import EditorStream, Operation, OperationStep, now
from app.schemas import CreateCampaign, DraftAction, OfferBinding


def bindings_dump(bindings: list[OfferBinding]) -> list[dict]:
    return [binding.model_dump() for binding in bindings]


def utc_timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def operation_view(operation: Operation, db: Session) -> dict:
    steps = db.scalars(
        select(OperationStep)
        .where(OperationStep.operation_id == operation.id)
        .order_by(OperationStep.id)
    ).all()
    return {
        "id": operation.id,
        "kind": operation.kind,
        "status": operation.status,
        "campaign_id": operation.campaign_id,
        "stream_id": operation.stream_id,
        "error": operation.error,
        "result": operation.result,
        "created_at": utc_timestamp(operation.created_at),
        "updated_at": utc_timestamp(operation.updated_at),
        "steps": [
            {
                "name": s.name,
                "status": s.status,
                "attempts": s.attempts,
                "error": s.error,
                "before": s.before,
                "after": s.after,
            }
            for s in steps
        ],
    }


class Operations:
    def __init__(self, db: Session):
        self.db = db

    def register(self, key: str, kind: str, request: dict) -> Operation:
        operation = self.db.scalar(select(Operation).where(Operation.key == key))
        request_hash = digest({"kind": kind, "request": request})
        if operation is None:
            operation = Operation(key=key, kind=kind, request=request, request_hash=request_hash)
            self.db.add(operation)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                operation = self.db.scalar(select(Operation).where(Operation.key == key))
        if operation is None or operation.request_hash != request_hash:
            raise AppError(
                "idempotency_conflict", "Этот ключ уже использован для другого запроса", 409
            )
        return operation

    def step(
        self,
        operation: Operation,
        name: str,
        action: Callable[[], dict],
        recover: Callable[[], dict | None] | None = None,
        before: dict | None = None,
        repeat_safe: bool = False,
    ) -> dict:
        step = self.db.scalar(
            select(OperationStep).where(
                OperationStep.operation_id == operation.id, OperationStep.name == name
            )
        )
        if step and step.status == "completed":
            return step.after or {}
        if step is None:
            step = OperationStep(operation_id=operation.id, name=name, before=before)
            self.db.add(step)
            self.db.commit()
        if step.status in {"running", "unknown"}:
            found = recover() if recover else None
            if found is not None:
                step.after, step.status, step.error = found, "completed", None
                self.db.commit()
                return found
            if not repeat_safe:
                raise KeitaroError(
                    "Результат записи пока не найден. Повтор POST заблокирован; "
                    "проверьте Keitaro и повторите сверку позже",
                    uncertain=True,
                )
        step.status, step.attempts, step.error = "running", step.attempts + 1, None
        self.db.commit()
        try:
            result = action()
        except AppError as error:
            step.status = (
                "unknown" if isinstance(error, KeitaroError) and error.uncertain else "failed"
            )
            step.error = error.message
            self.db.commit()
            raise
        step.after, step.status = result, "completed"
        self.db.commit()
        return result

    def fail(self, operation: Operation, error: AppError) -> None:
        operation.status = (
            "unknown" if isinstance(error, KeitaroError) and error.uncertain else "failed"
        )
        operation.error = error.message
        self.db.commit()


class CampaignService:
    def __init__(self, sessions: sessionmaker, client: KeitaroClient):
        self.sessions, self.client = sessions, client

    def create(self, request: CreateCampaign, key: str) -> dict:
        with resource_lock(self.sessions, f"create:{digest(key)}"), self.sessions() as db:
            journal = Operations(db)
            operation = journal.register(key, "create_campaign", request.model_dump())
            if operation.status == "completed":
                return operation_view(operation, db)
            operation.status, operation.error = "running", None
            db.commit()
            try:
                self._create(request, operation, journal)
            except AppError as error:
                journal.fail(operation, error)
            return operation_view(operation, db)

    def _create(self, request: CreateCampaign, operation: Operation, journal: Operations) -> None:
        refs = self.client.references()
        for collection, identifier in (
            ("domains", request.domain_id),
            ("groups", request.group_id),
            ("sources", request.traffic_source_id),
        ):
            if not any(
                item["id"] == identifier and item.get("state") != "deleted"
                for item in refs[collection]
            ):
                raise AppError("invalid_reference", f"Недоступный элемент справочника {collection}")
        offer = self.client.offer(request.offer_id)
        if offer.get("state") == "deleted":
            raise AppError("invalid_offer", "Выбранный оффер находится в архиве Keitaro")
        alias = "adrobot-" + operation.id.replace("-", "")
        campaign_body = {
            "name": request.name,
            "alias": alias,
            "state": "disabled",
            "type": "position",
            "domain_id": request.domain_id,
            "group_id": str(request.group_id),
            "traffic_source_id": request.traffic_source_id,
            "notes": f"adrobot-operation:{operation.id}",
        }

        def campaign_result(value: dict) -> dict:
            return {key: value.get(key) for key in ("id", "name", "alias", "state")}

        def recover_campaign() -> dict | None:
            found = self.client.find_campaign(alias)
            if found and found.get("notes") != campaign_body["notes"]:
                raise AppError("marker_conflict", "Alias занят кампанией без маркера операции", 409)
            return campaign_result(found) if found else None

        campaign = journal.step(
            operation,
            "create_campaign",
            lambda: campaign_result(self.client.create_campaign(campaign_body)),
            recover_campaign,
        )
        operation.campaign_id = campaign["id"]
        journal.db.commit()
        stream_specs = [
            {
                "name": "Geo · Google",
                "type": "regular",
                "position": 1,
                "schema": "redirect",
                "action_type": "http",
                "action_payload": "https://google.com",
                "filters": [{"name": "country", "mode": "accept", "payload": [request.country]}],
                "offers": [],
            },
            {
                "name": "Offers · All other visitors",
                "type": "regular",
                "position": 2,
                "schema": "landings",
                "action_type": "http",
                "filters": [],
                "landings": [],
                "offers": [{"offer_id": request.offer_id, "share": 100, "state": "active"}],
            },
        ]
        stream_ids = []
        for index, spec in enumerate(stream_specs):
            marker = f"adrobot-operation:{operation.id}:stream:{index}"
            body = {
                **spec,
                "campaign_id": campaign["id"],
                "state": "active",
                "collect_clicks": True,
                "filter_or": False,
                "comments": marker,
            }

            def recover_stream(marker: str = marker) -> dict | None:
                found = [
                    s for s in self.client.streams(campaign["id"]) if s.get("comments") == marker
                ]
                if len(found) > 1:
                    raise AppError(
                        "marker_conflict", "Найдено несколько потоков с одним маркером", 409
                    )
                return {"id": found[0]["id"]} if found else None

            stream = journal.step(
                operation,
                f"create_stream_{index}",
                lambda body=body: {"id": self.client.create_stream(body)["id"]},
                recover_stream,
            )
            stream_ids.append(stream["id"])
        actual_campaign = self.client.campaign(campaign["id"])
        actual_streams = self.client.streams(campaign["id"])
        self._verify(request, actual_campaign, actual_streams, stream_ids)

        def enable() -> dict:
            self.client.enable_campaign(campaign["id"])
            current = self.client.campaign(campaign["id"])
            if current.get("state") != "active":
                raise KeitaroError("Keitaro не подтвердил включение кампании", uncertain=True)
            return {"id": current["id"], "state": "active"}

        journal.step(
            operation,
            "enable_campaign",
            enable,
            lambda: (
                {"id": campaign["id"], "state": "active"}
                if self.client.campaign(campaign["id"]).get("state") == "active"
                else None
            ),
            repeat_safe=True,
        )
        operation.status, operation.error = "completed", None
        operation.result = {"campaign_id": campaign["id"], "alias": alias, "stream_ids": stream_ids}
        journal.db.commit()

    @staticmethod
    def _verify(
        request: CreateCampaign, campaign: dict, streams: list[dict], ids: list[int]
    ) -> None:
        if (
            campaign.get("type") != "position"
            or str(campaign.get("group_id")) != str(request.group_id)
            or campaign.get("domain_id") != request.domain_id
            or campaign.get("traffic_source_id") != request.traffic_source_id
            or len(streams) != 2
            or {s["id"] for s in streams} != set(ids)
        ):
            raise AppError(
                "verification_failed", "Конфигурация кампании отличается от ожидаемой", 409
            )
        first, second = (
            next(s for s in streams if s["id"] == ids[0]),
            next(s for s in streams if s["id"] == ids[1]),
        )
        filters = first.get("filters", [])
        if (
            first.get("position") != 1
            or first.get("state") != "active"
            or first.get("type") != "regular"
            or first.get("schema") != "redirect"
            or first.get("action_type") != "http"
            or first.get("offers")
            or (first.get("action_payload") or "").rstrip("/") != "https://google.com"
            or len(filters) != 1
            or not any(
                f.get("name") == "country"
                and f.get("mode") == "accept"
                and f.get("payload") == [request.country]
                for f in filters
            )
            or second.get("position") != 2
            or second.get("state") != "active"
            or second.get("type") != "regular"
            or second.get("filters")
            or second.get("landings")
            or second.get("schema") != "landings"
            or [
                {"offer_id": b["offer_id"], "share": b["share"], "state": b.get("state", "active")}
                for b in second["offers"]
            ]
            != [{"offer_id": request.offer_id, "share": 100, "state": "active"}]
        ):
            raise AppError(
                "verification_failed", "Потоки не прошли проверку; кампания не включена", 409
            )


class EditorService:
    def __init__(self, sessions: sessionmaker, client: KeitaroClient):
        self.sessions, self.client = sessions, client

    @staticmethod
    def view(row: EditorStream) -> dict:
        return {
            "stream_id": row.stream_id,
            "campaign_id": row.campaign_id,
            "name": row.snapshot.get("name", f"Поток {row.stream_id}"),
            "type": row.snapshot.get("type"),
            "version": row.version,
            "dirty": row.dirty,
            "bindings": row.draft,
            "synced_at": row.synced_at,
            "editable": bool(row.baseline or row.archive or row.draft),
            "deleted": row.snapshot.get("state") == "deleted",
            "pending_operation_id": row.pending_operation_id,
        }

    def list(self, campaign_id: int) -> list[dict]:
        with self.sessions() as db:
            return [
                self.view(row)
                for row in db.scalars(
                    select(EditorStream)
                    .where(EditorStream.campaign_id == campaign_id)
                    .order_by(EditorStream.stream_id)
                )
            ]

    @staticmethod
    def _remote_bindings(stream: dict, old: list[dict], names: dict[int, str]) -> list[dict]:
        previous = {b["offer_id"]: b for b in old}
        result = []
        for binding in stream["offers"]:
            identifier = binding["offer_id"]
            result.append(
                OfferBinding(
                    offer_id=identifier,
                    share=binding["share"],
                    state=binding.get("state", "active"),
                    name=names.get(
                        identifier, previous.get(identifier, {}).get("name", f"Оффер #{identifier}")
                    ),
                    pinned=previous.get(identifier, {}).get("pinned", False),
                ).model_dump()
            )
        return result

    def fetch(self, campaign_id: int) -> list[dict]:
        with resource_lock(self.sessions, f"campaign:{campaign_id}"), self.sessions() as db:
            self.client.campaign(campaign_id)
            streams = self.client.streams(campaign_id)
            offers = self.client.offers()
            names = {offer["id"]: offer.get("name", f"Оффер #{offer['id']}") for offer in offers}
            rows = list(
                db.scalars(select(EditorStream).where(EditorStream.campaign_id == campaign_id))
            )
            existing = {row.stream_id: row for row in rows}
            incoming = {stream["id"]: stream for stream in streams}
            for row in rows:
                if row.pending_operation_id:
                    raise AppError(
                        "pending_publication", "Сначала завершите незавершённую публикацию", 409
                    )
                if row.dirty and (
                    row.stream_id not in incoming
                    or stream_fingerprint(row.snapshot)
                    != stream_fingerprint(incoming[row.stream_id])
                ):
                    raise AppError(
                        "external_conflict",
                        "Keitaro изменился при наличии черновика. "
                        "Отмените черновик перед повторным Fetch",
                        409,
                    )
            for stream in streams:
                row = existing.get(stream["id"])
                if row and row.dirty:
                    continue
                old = row.draft if row else []
                archive = row.archive if row else []
                current = self._remote_bindings(stream, old + archive, names)
                current_ids = {b["offer_id"] for b in current}
                archived = {b["offer_id"]: b for b in archive}
                for binding in old:
                    if binding["offer_id"] not in current_ids:
                        archived[binding["offer_id"]] = {**binding, "removed": True, "share": 0}
                archived = {k: v for k, v in archived.items() if k not in current_ids}
                if row is None:
                    row = EditorStream(stream_id=stream["id"], campaign_id=campaign_id)
                    db.add(row)
                    row.version = 0
                row.snapshot, row.baseline = stream, current
                row.archive = list(archived.values())
                row.draft = current + row.archive
                row.version += 1
                row.dirty, row.synced_at = False, now()
            for row in rows:
                if row.stream_id not in incoming:
                    # Keep its binding archive/history, but show the remote deletion explicitly
                    row.snapshot = {**row.snapshot, "state": "deleted"}
                    row.draft = [{**b, "removed": True, "share": 0} for b in row.draft]
                    row.archive, row.baseline = row.draft, []
                    row.version += 1
            db.commit()
            return [
                self.view(row)
                for row in db.scalars(
                    select(EditorStream)
                    .where(EditorStream.campaign_id == campaign_id)
                    .order_by(EditorStream.stream_id)
                )
            ]

    def _campaign_id(self, stream_id: int) -> int:
        with self.sessions() as db:
            row = db.get(EditorStream, stream_id)
            if row is None:
                raise AppError("not_found", "Сначала загрузите потоки кампании через Fetch", 404)
            return row.campaign_id

    @staticmethod
    def _check(row: EditorStream, version: int) -> None:
        if row.version != version:
            raise AppError(
                "version_conflict", "Черновик изменён в другой вкладке. Обновите данные", 409
            )
        if row.pending_operation_id:
            raise AppError(
                "pending_publication", "Сначала завершите или сверяйте текущую публикацию", 409
            )
        if row.snapshot.get("state") == "deleted":
            raise AppError("deleted_stream", "Поток удалён в Keitaro", 409)

    def edit(self, stream_id: int, action: DraftAction) -> dict:
        campaign_id = self._campaign_id(stream_id)
        with resource_lock(self.sessions, f"campaign:{campaign_id}"), self.sessions() as db:
            row = db.get(EditorStream, stream_id)
            self._check(row, action.version)
            if not (row.baseline or row.archive):
                raise AppError(
                    "unsupported_stream", "Потоки без офферов доступны только для просмотра"
                )
            bindings = [OfferBinding(**binding) for binding in row.draft]
            target = next((b for b in bindings if b.offer_id == action.offer_id), None)
            if action.action == "add":
                if target:
                    raise AppError(
                        "duplicate_offer", "Оффер уже известен потоку; используйте Bring back", 409
                    )
                offer = self.client.offer(action.offer_id)
                if offer.get("state") == "deleted":
                    raise AppError("invalid_offer", "Оффер находится в архиве Keitaro")
                bindings.append(
                    OfferBinding(offer_id=action.offer_id, name=offer.get("name", ""), share=0)
                )
            else:
                if target is None:
                    raise AppError("not_found", "Привязка оффера не найдена", 404)
                if action.action == "restore":
                    if not target.removed:
                        raise AppError("invalid_action", "Привязка уже активна", 409)
                    offer = self.client.offer(target.offer_id)
                    if offer.get("state") == "deleted":
                        raise AppError(
                            "invalid_offer", "Сам оффер удалён в Keitaro, вернуть привязку нельзя"
                        )
                    target.removed, target.pinned, target.state = False, False, "active"
                elif target.removed:
                    raise AppError("invalid_action", "Сначала верните привязку из архива", 409)
                elif action.action == "remove":
                    target.removed, target.share, target.pinned = True, 0, False
                elif action.action == "pin":
                    target.pinned = True
                elif action.action == "unpin":
                    target.pinned = False
                elif action.action == "set_share":
                    if action.share is None:
                        raise AppError("missing_share", "Укажите долю")
                    target.share, target.pinned = action.share, True
            row.draft = bindings_dump(rebalance(bindings))
            row.dirty, row.version = True, row.version + 1
            db.commit()
            return self.view(row)

    def cancel(self, stream_id: int, version: int) -> dict:
        campaign_id = self._campaign_id(stream_id)
        with resource_lock(self.sessions, f"campaign:{campaign_id}"), self.sessions() as db:
            row = db.get(EditorStream, stream_id)
            self._check(row, version)
            row.draft = row.baseline + row.archive
            row.dirty, row.version = False, row.version + 1
            db.commit()
            return self.view(row)

    def publish(self, stream_id: int, version: int, key: str) -> dict:
        campaign_id = self._campaign_id(stream_id)
        with resource_lock(self.sessions, f"campaign:{campaign_id}"), self.sessions() as db:
            journal = Operations(db)
            operation = journal.register(
                key, "publish_stream", {"stream_id": stream_id, "version": version}
            )
            if operation.status == "completed":
                return operation_view(operation, db)
            row = db.get(EditorStream, stream_id)
            if row.pending_operation_id not in {None, operation.id}:
                raise AppError("pending_publication", "Другой запрос уже публикует этот поток", 409)
            if row.pending_operation_id is None:
                self._check(row, version)
                if not row.dirty:
                    raise AppError("no_changes", "Нет изменений для публикации", 409)
            operation.stream_id, operation.campaign_id = stream_id, campaign_id
            row.pending_operation_id = operation.id
            operation.status, operation.error = "running", None
            db.commit()
            try:
                self._publish(row, operation, journal)
            except AppError as error:
                journal.fail(operation, error)
                # Only retain the fence when a write could have happened
                step = db.scalar(
                    select(OperationStep).where(
                        OperationStep.operation_id == operation.id,
                        OperationStep.name == "update_offers",
                    )
                )
                if step is None or step.status == "failed":
                    row.pending_operation_id = None
                    db.commit()
            return operation_view(operation, db)

    def _publish(self, row: EditorStream, operation: Operation, journal: Operations) -> None:
        bindings = [OfferBinding(**binding) for binding in row.draft]
        payload = offer_payload(bindings)
        active = [b for b in bindings if not b.removed and b.state == "active"]
        if not active or sum(b.share for b in active) != 100:
            raise AppError("invalid_shares", "Сумма долей активных офферов должна равняться 100%")
        current = self.client.stream(row.stream_id)
        intended = {**row.snapshot, "offers": payload}
        expected_hash = stream_fingerprint(intended)
        current_hash = stream_fingerprint(current)
        prior = journal.db.scalar(
            select(OperationStep).where(
                OperationStep.operation_id == operation.id, OperationStep.name == "update_offers"
            )
        )
        if current_hash == expected_hash and prior is not None:
            prior.status, prior.after, prior.error = "completed", {"offers": payload}, None
            journal.db.commit()
        elif current_hash != stream_fingerprint(row.snapshot):
            raise AppError(
                "external_conflict", "Поток изменён в Keitaro. Публикация остановлена", 409
            )
        else:
            journal.step(
                operation,
                "update_offers",
                lambda: self._write_offers(row.stream_id, payload),
                lambda: (
                    {"offers": payload}
                    if stream_fingerprint(self.client.stream(row.stream_id)) == expected_hash
                    else None
                ),
                before={"offers": offer_payload([OfferBinding(**b) for b in row.baseline])},
                repeat_safe=True,
            )
        confirmed = self.client.stream(row.stream_id)
        if stream_fingerprint(confirmed) != expected_hash:
            raise KeitaroError(
                "Ответ записи получен, но итоговая сверка отличается. "
                "Требуется проверка перед дальнейшим редактированием",
                uncertain=True,
            )
        removed = [b.model_dump() for b in bindings if b.removed]
        published = [b.model_dump() for b in bindings if not b.removed]
        row.snapshot, row.baseline, row.archive = confirmed, published, removed
        row.draft, row.dirty = published + removed, False
        row.version += 1
        row.pending_operation_id, row.synced_at = None, now()
        operation.status, operation.result, operation.error = (
            "completed",
            {"stream_id": row.stream_id},
            None,
        )
        journal.db.commit()

    def _write_offers(self, stream_id: int, payload: list[dict]) -> dict:
        self.client.update_offers(stream_id, payload)
        return {"offers": payload}

    def adopt_remote(self, stream_id: int, version: int) -> dict:
        """Explicitly resolve a publication conflict by adopting the current remote truth."""
        campaign_id = self._campaign_id(stream_id)
        with resource_lock(self.sessions, f"campaign:{campaign_id}"), self.sessions() as db:
            row = db.get(EditorStream, stream_id)
            if row.version != version:
                raise AppError("version_conflict", "Обновите данные перед сверкой", 409)
            current = self.client.stream(stream_id)
            names = {o["id"]: o.get("name", "") for o in self.client.offers()}
            baseline = self._remote_bindings(current, row.draft + row.archive, names)
            active_ids = {b["offer_id"] for b in baseline}
            removed = {
                b["offer_id"]: {**b, "share": 0, "removed": True}
                for b in row.baseline + row.archive
                if b["offer_id"] not in active_ids
            }
            if row.pending_operation_id:
                operation = db.get(Operation, row.pending_operation_id)
                operation.status, operation.error = (
                    "resolved",
                    "Пользователь принял состояние Keitaro",
                )
            row.snapshot, row.baseline, row.archive = current, baseline, list(removed.values())
            row.draft, row.dirty = baseline + row.archive, False
            row.pending_operation_id, row.synced_at = None, now()
            row.version += 1
            db.commit()
            return self.view(row)


def operation_age_seconds(operation: Operation) -> float:
    timestamp = operation.updated_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return (datetime.now(UTC) - timestamp).total_seconds()
