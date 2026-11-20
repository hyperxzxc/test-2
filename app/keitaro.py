import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.errors import KeitaroError


class RemoteObject(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int = Field(gt=0)


class RemoteStream(RemoteObject):
    campaign_id: int = Field(gt=0)
    offers: list[dict]


T = TypeVar("T", bound=RemoteObject)


class KeitaroClient:
    """The only HTTP boundary. Mutating requests are deliberately never retried here."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.configured = bool(settings.keitaro_api_key.get_secret_value())
        self.http = httpx.Client(
            base_url=f"{settings.keitaro_base_url}/admin_api/v1/",
            headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
            timeout=settings.keitaro_timeout,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self.http.close()

    def _request(
        self, method: str, path: str, body: dict | None = None, params: dict | None = None
    ) -> object:
        if not self.configured:
            raise KeitaroError("Укажите KEITARO_API_KEY в серверном .env")
        write = method != "GET"
        for attempt in range(2 if not write else 1):
            try:
                response = self.http.request(method, path, json=body, params=params)
            except httpx.RequestError:
                if not write and attempt == 0:
                    time.sleep(0.1)
                    continue
                raise KeitaroError(
                    "Keitaro недоступен или превысил время ожидания", uncertain=write
                ) from None
            if (
                not write
                and attempt == 0
                and (response.status_code >= 500 or response.status_code == 429)
            ):
                time.sleep(0.1)
                continue
            if response.is_error or response.is_redirect:
                messages = {
                    401: "Keitaro отклонил API-ключ",
                    403: "Недостаточно прав Keitaro",
                    402: "Admin API недоступен в текущей лицензии Keitaro",
                    404: "Сущность не найдена в Keitaro",
                    429: "Лимит запросов Keitaro",
                }
                raise KeitaroError(
                    messages.get(response.status_code, "Ошибка ответа Keitaro"),
                    response.status_code,
                    uncertain=write and response.status_code >= 500,
                )
            if not response.content:
                if method == "POST" and path.endswith(("/enable", "/disable")):
                    return {}
                raise KeitaroError("Keitaro вернул пустой ответ", uncertain=write)
            try:
                return response.json()
            except ValueError:
                raise KeitaroError("Keitaro вернул некорректный JSON", uncertain=write) from None
        raise AssertionError("unreachable")

    def _object(
        self, method: str, path: str, body: dict | None = None, model: type[T] = RemoteObject
    ) -> dict:
        value = self._request(method, path, body)
        try:
            parsed = model.model_validate(value)
            if isinstance(parsed, RemoteStream):
                self._validate_offers(parsed.offers)
            return parsed.model_dump(mode="json")
        except (ValidationError, ValueError, TypeError):
            raise KeitaroError(
                "Ответ Keitaro не соответствует контракту", uncertain=method != "GET"
            ) from None

    @staticmethod
    def _validate_offers(offers: list[dict]) -> None:
        seen: set[int] = set()
        for offer in offers:
            identifier = offer.get("offer_id")
            share = offer.get("share")
            if (
                not isinstance(identifier, int)
                or identifier <= 0
                or identifier in seen
                or not isinstance(share, int)
                or not 0 <= share <= 100
                or offer.get("state", "active") not in {"active", "disabled"}
            ):
                raise ValueError("Invalid offer binding")
            seen.add(identifier)

    def _list(
        self, path: str, params: dict | None = None, model: type[RemoteObject] = RemoteObject
    ) -> list[dict]:
        value = self._request("GET", path, params=params)
        try:
            if not isinstance(value, list):
                raise ValueError("Expected a complete list")
            result = [model.model_validate(item).model_dump(mode="json") for item in value]
            if len({item["id"] for item in result}) != len(result):
                raise ValueError("Duplicate entities")
            if model is RemoteStream:
                for stream in result:
                    self._validate_offers(stream["offers"])
            return result
        except (ValidationError, ValueError, TypeError):
            raise KeitaroError(
                "Keitaro вернул некорректный список; синхронизация отменена"
            ) from None

    def references(self) -> dict:
        return {
            "domains": self._list("domains"),
            "groups": self._list("groups", {"type": "campaigns"}),
            "sources": self._list("traffic_sources"),
        }

    def campaigns(self, offset: int = 0, limit: int = 50) -> list[dict]:
        return self._list("campaigns", {"offset": offset, "limit": limit})

    def campaign(self, identifier: int) -> dict:
        return self._object("GET", f"campaigns/{identifier}")

    def offers(self) -> list[dict]:
        return self._list("offers")

    def offer(self, identifier: int) -> dict:
        return self._object("GET", f"offers/{identifier}")

    def streams(self, campaign_id: int) -> list[dict]:
        result = self._list(f"campaigns/{campaign_id}/streams", model=RemoteStream)
        if any(s["campaign_id"] != campaign_id for s in result):
            raise KeitaroError("Keitaro вернул потоки другой кампании")
        return result

    def stream(self, identifier: int) -> dict:
        return self._object("GET", f"streams/{identifier}", model=RemoteStream)

    def create_campaign(self, body: dict) -> dict:
        return self._object("POST", "campaigns", body)

    def create_stream(self, body: dict) -> dict:
        return self._object("POST", "streams", body, RemoteStream)

    def update_offers(self, identifier: int, offers: list[dict]) -> dict:
        # Replace bindings only. Never send DELETE /offers or unrelated stream settings
        return self._object("PUT", f"streams/{identifier}", {"offers": offers}, RemoteStream)

    def enable_campaign(self, identifier: int) -> None:
        self._request("POST", f"campaigns/{identifier}/enable")

    def find_campaign(self, alias: str) -> dict | None:
        offset = 0
        while True:
            batch = self.campaigns(offset, 100)
            matches = [campaign for campaign in batch if campaign.get("alias") == alias]
            if len(matches) > 1:
                raise KeitaroError("Найдено несколько кампаний с маркером операции")
            if matches:
                return matches[0]
            if len(batch) < 100:
                return None
            offset += len(batch)
            if offset >= 10000:
                raise KeitaroError(
                    "Не удалось однозначно проверить кампанию: слишком большой список"
                )
