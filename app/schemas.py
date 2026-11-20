import re
from datetime import datetime
from typing import Literal

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateCampaign(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    traffic_source_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название не должно быть пустым")
        return value

    @field_validator("country")
    @classmethod
    def country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value) or not pycountry.countries.get(alpha_2=value):
            raise ValueError("Нужен действительный ISO 3166-1 alpha-2 код страны")
        return value


class OfferBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: int = Field(gt=0)
    name: str = ""
    share: int = Field(ge=0, le=100)
    state: Literal["active", "disabled"] = "active"
    pinned: bool = False
    removed: bool = False


class DraftAction(BaseModel):
    version: int = Field(gt=0)
    action: Literal["add", "remove", "restore", "pin", "unpin", "set_share"]
    offer_id: int = Field(gt=0)
    share: int | None = Field(default=None, ge=0, le=100)


class VersionRequest(BaseModel):
    version: int = Field(gt=0)


class StepRead(BaseModel):
    name: str
    status: str
    attempts: int
    error: str | None
    before: dict | None
    after: dict | None


class OperationRead(BaseModel):
    id: str
    kind: str
    status: str
    campaign_id: int | None
    stream_id: int | None
    error: str | None
    result: dict | None
    created_at: datetime
    updated_at: datetime
    steps: list[StepRead]


class StreamRead(BaseModel):
    stream_id: int
    campaign_id: int
    name: str
    type: str | None
    version: int
    dirty: bool
    bindings: list[OfferBinding]
    synced_at: datetime
    editable: bool
    deleted: bool
    pending_operation_id: str | None


class ReferenceRead(BaseModel):
    id: int
    name: str = ""
    domain: str | None = None
    state: str | None = None


class CampaignRead(ReferenceRead):
    alias: str | None = None
