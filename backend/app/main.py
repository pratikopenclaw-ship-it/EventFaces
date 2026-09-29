from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from app.api.csrf import CSRFMiddleware
from app.api.routes import auth, events, invites, join, members, moderation, photos, privacy, search, uploads
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="EventFaces API",
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    app.add_middleware(CSRFMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

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
