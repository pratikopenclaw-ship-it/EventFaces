import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError
from starlette.requests import Request
from starlette.responses import Response

from app.api.csrf import CSRFMiddleware
from app.api.routes import auth, events, invites, join, members, moderation, photos, privacy, search, uploads
from app.core.config import get_settings
from app.core.logging import install as redact_access_logs

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    redact_access_logs()
    app = FastAPI(
        title="EventFaces API",
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.add_middleware(CSRFMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

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
    ):
        app.include_router(router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
