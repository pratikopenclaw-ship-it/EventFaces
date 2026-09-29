from fastapi import Request

from app.core import rate_limit
from app.core.config import get_settings


def _request(xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": ("10.0.0.5", 1234)})


def test_spoofed_forwarded_for_is_ignored_by_default() -> None:
    assert rate_limit.client_ip(_request("6.6.6.6")) == "10.0.0.5"


def test_trusted_hop_uses_entry_appended_by_our_proxy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 1)
    # client spoofed "6.6.6.6"; our edge proxy appended the real address
    assert rate_limit.client_ip(_request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"
    assert rate_limit.client_ip(_request(None)) == "10.0.0.5"
