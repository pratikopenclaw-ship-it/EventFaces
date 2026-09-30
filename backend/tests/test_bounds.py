"""Negative and boundary inputs on query parameters (Phase B §9 / Phase C): never a 5xx,
never an unbounded result."""

import pytest

from tests.conftest import PASSWORD, new_client
from tests.test_authz_matrix import World, world  # noqa: F401  (fixture re-export)


@pytest.mark.parametrize(
    "query",
    [
        "/search-log?limit=-1",
        "/search-log?limit=0",
        "/search-log?limit=100000000",
        "/search-log?limit=99999999999999999999999",
        "/search-log?limit=abc",
        "/photos?offset=-1",
        "/photos?offset=99999999999999999999999",
        "/photos?limit=0",
        "/photos?limit=201",
        "/photos?status=nope",
        "/reports?include_resolved=maybe",
    ],
)
def test_out_of_range_query_params_are_422(world: World, query: str) -> None:  # noqa: F811
    c = new_client()
    assert c.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD}).status_code == 200
    r = c.get(f"/api/events/{world.event_a.id}{query}")
    assert r.status_code == 422, (query, r.status_code, r.text[:200])


@pytest.mark.parametrize("bad", ["not-a-uuid", "00000000-0000-0000-0000-00000000000g", "%00", "..%2F..%2Fetc", "1" * 5000])
def test_malformed_path_ids_are_rejected_not_crashing(world: World, bad: str) -> None:  # noqa: F811
    c = new_client()
    c.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    for path in (f"/api/events/{bad}", f"/api/events/{world.event_a.id}/photos/{bad}/thumb", f"/api/downloads/{bad}", f"/api/invites/{bad}"):
        r = c.get(path)
        assert r.status_code < 500, (path, r.status_code)
