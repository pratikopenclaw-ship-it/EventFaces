import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.requests import Request
from starlette.responses import Response

from app.api.app_version import AppVersionMiddleware
from app.api.csrf import CSRFMiddleware
from app.api.routes import auth, billing, contact, events, invites, join, legal, members, mobile, moderation, photos, privacy, search, uploads
from app.core.config import get_settings
from app.core import monitoring
from app.core.logging import install as redact_access_logs
from app.core.security import HashingBusy

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    redact_access_logs()
    monitoring.init("api")
    app = FastAPI(
        title="EventFaces API",
        # Readable, stable operation ids for the generated iOS client (Swift method names).
        generate_unique_id_function=lambda route: f"{route.tags[0]}_{route.name}" if route.tags else route.name,
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(AppVersionMiddleware)  # outermost of the two: outdated apps stop here

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.exception_handler(HashingBusy)
    async def hashing_busy(request: Request, exc: HashingBusy) -> Response:
        return JSONResponse(
            {"detail": "Lots of people are signing in right now. Please try again in a few seconds."},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(PoolTimeout)
    async def pool_exhausted(request: Request, exc: PoolTimeout) -> Response:
        # Overload, not a bug: answer like every other capacity limit (SEC-042).
        log.warning("Database connection pool exhausted")
        return JSONResponse(
            {"detail": "The service is very busy right now. Please try again in a few seconds."},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> Response:
        # FastAPI's default echoes each rejected value ("input"): passwords, card numbers,
        # tokens. Keep where and why it failed, never what was sent.
        errors = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(DataError)
    async def invalid_data(request: Request, exc: DataError) -> Response:
        # Input the database can't store (NUL bytes in text, out-of-range numbers) is the
        # client's fault: 422, not a 500. Log the class only, never the offending value.
        log.warning("Rejected unstorable input: %s", type(exc.orig).__name__)
        return JSONResponse({"detail": "The request contains characters or values that aren't allowed."}, status_code=422)

    for router in (
        auth.router,
        auth.me_router,
        events.router,
        members.router,
        join.router,
        photos.router,
        search.router,
        uploads.router,
        moderation.router,
        invites.router,
        privacy.router,
        mobile.router,
        mobile.me_router,
        legal.router,
        billing.router,
        contact.router,
    ):
        app.include_router(router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
