"""Error reporting to the self-hosted GlitchTip (Sentry protocol). Off unless SENTRY_DSN is set.

Privacy first, because the API handles biometric data:
- no request bodies (raw selfie bodies must never leave the process), cookies, auth headers,
  query strings or local variables;
- URLs and messages pass through `core.logging.redact` (tokens in links), and emails and
  bearer tokens are removed;
- users are identified by their opaque id only (no email, no IP).
`scrub` is the single filter for everything sent; `tests/test_monitoring.py` enforces it.
"""

import logging
import re
from typing import Any, cast

from app.core.config import get_settings
from app.core.logging import redact

log = logging.getLogger(__name__)

# Request headers that carry no personal data and help triage.
SAFE_HEADERS = {"content-type", "content-length", "x-app-version", "accept"}


# Beyond the access-log patterns: a bare `token=…` / `code=…` / `password=…` anywhere in
# text, email addresses (exception messages may name a user) and bearer tokens.
_SECRET_ASSIGNMENT = re.compile(r"(?i)\b(token|code|password|secret|signature|key)=([^&\s\"',)]+)")
_EMAIL = re.compile(r"[^\s@\"'<>(),;:]+@[^\s@\"'<>(),;:]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _redact(value: str) -> str:
    value = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", redact(value))
    return _BEARER.sub("[redacted]", _EMAIL.sub("[email]", value))


def _clean_text(value: Any) -> Any:
    return _redact(value) if isinstance(value, str) else value


def scrub(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove everything that could carry personal data or secrets."""
    request = event.get("request")
    if isinstance(request, dict):
        url = request.get("url")
        event["request"] = {
            "method": request.get("method"),
            "url": _redact(url.split("?")[0]) if isinstance(url, str) else None,
            "headers": {k: v for k, v in (request.get("headers") or {}).items() if k.lower() in SAFE_HEADERS},
        }
    user = event.get("user")
    event["user"] = {"id": str(user["id"])} if isinstance(user, dict) and user.get("id") else {}
    # `_meta` only notes which fields the SDK removed; drop it so not even their names go out.
    for key in ("extra", "server_name", "_meta"):
        event.pop(key, None)
    if isinstance(event.get("message"), str):
        event["message"] = _redact(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        logentry["message"] = _clean_text(logentry.get("message"))
        logentry["formatted"] = _clean_text(logentry.get("formatted"))
        logentry.pop("params", None)
    for exc in (event.get("exception") or {}).get("values") or []:
        exc["value"] = _clean_text(exc.get("value"))
        for frame in (exc.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    crumbs = event.get("breadcrumbs")
    for crumb in (crumbs.get("values") if isinstance(crumbs, dict) else crumbs) or []:
        crumb["message"] = _clean_text(crumb.get("message"))
        crumb.pop("data", None)  # HTTP breadcrumbs carry URLs and query strings
    return event


def init(component: str, transport: Any = None) -> bool:
    """Start reporting for `component` ("api" or "worker"); returns whether it is on.
    `transport` is for tests (capture events instead of sending them)."""
    s = get_settings()
    if not s.sentry_dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.environment,
        release=s.app_version,
        server_name=component,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=s.sentry_traces_sample_rate,
        before_send=cast(Any, scrub),  # the SDK's Event TypedDict is a plain dict at runtime
        before_send_transaction=cast(Any, scrub),
        transport=transport,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    sentry_sdk.set_tag("component", component)
    return True


def set_user(user_id: object) -> None:
    """Attach the opaque user id to errors in this request (never email or IP)."""
    if not get_settings().sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.set_user({"id": str(user_id)})


def heartbeat(url: str) -> bool:
    """Check in with a GlitchTip heartbeat monitor (it alerts when check-ins stop). Sends no
    data; never raises, so a monitoring outage can't fail the job that reports to it."""
    if not url:
        return False
    import httpx

    try:
        return httpx.post(url, timeout=5).is_success
    except httpx.HTTPError:
        log.warning("heartbeat check-in failed")
        return False
