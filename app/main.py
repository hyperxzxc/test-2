import logging
import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import pycountry
from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from app.config import Settings, get_settings
from app.db import make_session_factory
from app.errors import AppError
from app.keitaro import KeitaroClient
from app.models import Operation
from app.schemas import (
    CampaignRead,
    CreateCampaign,
    DraftAction,
    OperationRead,
    ReferenceRead,
    StreamRead,
    VersionRequest,
)
from app.services import CampaignService, EditorService, operation_view

logger = logging.getLogger("keitaro_desk")
Identifier = Annotated[int, Path(gt=0)]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]


def create_app(settings: Settings | None = None, client: KeitaroClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine, sessions = make_session_factory(settings.database_url)
    remote = client or KeitaroClient(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("Keitaro Desk started")
        yield
        remote.close()
        engine.dispose()
        logger.info("Keitaro Desk stopped")

    application = FastAPI(
        title="Keitaro Desk",
        version="1.0.0",
        lifespan=lifespan,
        description="Создание кампаний и редактор привязок с черновиками",
    )
    application.state.engine, application.state.sessions = engine, sessions
    creator, editor = CampaignService(sessions, remote), EditorService(sessions, remote)

    @application.middleware("http")
    async def request_id(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", incoming) else str(uuid4())
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @application.exception_handler(AppError)
    async def application_error(request: Request, error: AppError):
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [
            {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Проверьте поля запроса",
                    "details": details,
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        # Do not log exception text: HTTP errors may embed request URLs/credentials
        logger.error("Unhandled %s request_id=%s", type(error).__name__, request.state.request_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка сервера",
                    "request_id": request.state.request_id,
                }
            },
        )

    def authorize(x_app_token: Annotated[str | None, Header()] = None):
        token = settings.app_access_token.get_secret_value()
        if token and not secrets.compare_digest(token, x_app_token or ""):
            raise AppError("unauthorized", "Нужен токен доступа к обёртке", 401)

    api = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @api.get("/meta", tags=["Configuration"])
    def meta():
        return {
            "configured": remote.configured,
            "demo_mode": settings.demo_mode,
            "defaults": {
                "domain_id": settings.default_domain_id,
                "group_id": settings.default_group_id,
                "traffic_source_id": settings.default_traffic_source_id,
            },
        }

    @api.get("/references", tags=["Configuration"])
    def references():
        return {
            **{
                key: [ReferenceRead.model_validate(item).model_dump() for item in items]
                for key, items in remote.references().items()
            },
            "countries": sorted(
                [{"code": c.alpha_2, "name": c.name} for c in pycountry.countries],
                key=lambda country: country["name"],
            ),
        }

    @api.get("/campaigns", tags=["Campaigns"], response_model=list[CampaignRead])
    def campaigns(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return remote.campaigns(offset, limit)

    @api.post("/campaigns", tags=["Campaigns"], response_model=OperationRead)
    def create_campaign(body: CreateCampaign, key: IdempotencyKey):
        return creator.create(body, key)

    @api.get("/offers", tags=["Offers"], response_model=list[ReferenceRead])
    def offers(q: str = Query("", max_length=200)):
        query = q.strip().casefold()
        return [
            o
            for o in remote.offers()
            if o.get("state") != "deleted"
            and (not query or query in str(o["id"]) or query in o.get("name", "").casefold())
        ][:100]

    @api.post("/campaigns/{campaign_id}/fetch", tags=["Editor"], response_model=list[StreamRead])
    def fetch(campaign_id: Identifier):
        return editor.fetch(campaign_id)

    @api.get("/campaigns/{campaign_id}/streams", tags=["Editor"], response_model=list[StreamRead])
    def streams(campaign_id: Identifier):
        return editor.list(campaign_id)

    @api.patch("/streams/{stream_id}/draft", tags=["Editor"], response_model=StreamRead)
    def edit(stream_id: Identifier, body: DraftAction):
        return editor.edit(stream_id, body)

    @api.post("/streams/{stream_id}/cancel", tags=["Editor"], response_model=StreamRead)
    def cancel(stream_id: Identifier, body: VersionRequest):
        return editor.cancel(stream_id, body.version)

    @api.post("/streams/{stream_id}/publish", tags=["Editor"], response_model=OperationRead)
    def publish(stream_id: Identifier, body: VersionRequest, key: IdempotencyKey):
        return editor.publish(stream_id, body.version, key)

    @api.post("/streams/{stream_id}/adopt-remote", tags=["Editor"], response_model=StreamRead)
    def adopt_remote(stream_id: Identifier, body: VersionRequest):
        return editor.adopt_remote(stream_id, body.version)

    @api.get("/operations", tags=["Operations"], response_model=list[OperationRead])
    def operations():
        with sessions() as db:
            return [
                operation_view(operation, db)
                for operation in db.scalars(
                    select(Operation).order_by(Operation.created_at.desc()).limit(50)
                )
            ]

    @api.get("/operations/{operation_id}", tags=["Operations"], response_model=OperationRead)
    def operation(operation_id: str):
        with sessions() as db:
            row = db.get(Operation, operation_id)
            if row is None:
                raise AppError("not_found", "Операция не найдена", 404)
            return operation_view(row, db)

    @api.post("/operations/{operation_id}/retry", tags=["Operations"], response_model=OperationRead)
    def retry(operation_id: str):
        with sessions() as db:
            row = db.get(Operation, operation_id)
            if row is None:
                raise AppError("not_found", "Операция не найдена", 404)
            if row.status == "resolved":
                raise AppError("resolved_operation", "Операция завершена сверкой с Keitaro", 409)
            kind, payload, key = row.kind, row.request, row.key
        if kind == "create_campaign":
            return creator.create(CreateCampaign(**payload), key)
        return editor.publish(payload["stream_id"], payload["version"], key)

    application.include_router(api)

    @application.get("/live", include_in_schema=False)
    def live():
        return {"status": "alive"}

    @application.get("/ready", include_in_schema=False)
    def ready():
        try:
            with sessions() as db:
                db.execute(text("SELECT id FROM operations LIMIT 1"))
            if not remote.configured:
                return JSONResponse(status_code=503, content={"status": "missing_keitaro_key"})
            return {"status": "ready"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "database_unavailable"})

    if settings.frontend_dir.exists():
        application.mount(
            "/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend"
        )
    else:

        @application.get("/", include_in_schema=False)
        def frontend_help():
            if (settings.frontend_dir / "index.html").is_file():
                return FileResponse(settings.frontend_dir / "index.html")
            return {"message": "Frontend: npm ci && npm run build в frontend/", "docs": "/docs"}

    return application


app = create_app()
