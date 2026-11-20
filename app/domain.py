import hashlib
import json
from collections.abc import Sequence

from app.errors import AppError
from app.schemas import OfferBinding


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def rebalance(bindings: Sequence[OfferBinding]) -> list[OfferBinding]:
    result = [b.model_copy(deep=True) for b in bindings]
    active = [b for b in result if not b.removed and b.state == "active"]
    if not active:
        raise AppError("empty_stream", "В потоке должен остаться хотя бы один активный оффер")
    pinned = sum(b.share for b in active if b.pinned)
    if pinned > 100:
        raise AppError("invalid_shares", "Сумма закреплённых долей превышает 100%")
    free = [b for b in active if not b.pinned]
    if not free and pinned != 100:
        raise AppError("invalid_shares", "Все доли закреплены, но их сумма не равна 100%")
    if free:
        quotient, remainder = divmod(100 - pinned, len(free))
        for index, binding in enumerate(free):
            binding.share = quotient + int(remainder > 0 and index >= len(free) - remainder)
    for binding in result:
        if binding.removed or binding.state == "disabled":
            binding.share = 0
    return result


def offer_payload(bindings: Sequence[OfferBinding]) -> list[dict]:
    return [
        {"offer_id": b.offer_id, "share": b.share, "state": b.state}
        for b in bindings
        if not b.removed
    ]


def stream_fingerprint(stream: dict) -> str:
    # Relationship IDs and timestamps change independently of meaningful settings
    fields = (
        "id",
        "campaign_id",
        "name",
        "type",
        "schema",
        "state",
        "position",
        "weight",
        "action_type",
        "action_payload",
        "action_options",
        "filter_or",
        "filters",
        "landings",
        "offer_selection",
        "collect_clicks",
    )
    content = {key: stream[key] for key in fields if key in stream}
    # Keitaro normalizes an unused payload from null to "" on PUT /streams/{id}
    content["action_payload"] = stream.get("action_payload") or None
    content["offers"] = sorted(
        [
            {
                key: b.get(key, "active" if key == "state" else 0)
                for key in ("offer_id", "share", "state")
            }
            for b in stream["offers"]
        ],
        key=lambda b: b["offer_id"],
    )
    return digest(content)
