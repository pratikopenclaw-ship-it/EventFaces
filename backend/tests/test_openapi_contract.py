"""The iOS app's API client is generated from backend/openapi.json. If the API changes
without re-exporting it, the app would be built against stale types: fail instead.

Fix: docker compose exec api python -m app.cli export-openapi"""

from app.cli import OPENAPI_PATH, openapi_document


def test_committed_openapi_schema_is_current() -> None:
    assert OPENAPI_PATH.exists(), "run: python -m app.cli export-openapi"
    assert OPENAPI_PATH.read_text() == openapi_document(), "API changed: run `python -m app.cli export-openapi`"


def test_schema_documents_the_raw_image_bodies() -> None:
    import json

    doc = json.loads(openapi_document())
    logo = doc["paths"]["/api/events/{event_id}/logo"]["put"]["requestBody"]["content"]
    assert set(logo) == {"image/png", "image/jpeg", "image/heic"}


def test_operation_ids_are_unique_readable_swift_names() -> None:
    import json
    import re

    ids = [op["operationId"] for ops in json.loads(openapi_document())["paths"].values() for op in ops.values()]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids), [i for i in ids if not re.fullmatch(r"[a-z][a-z0-9_]*", i)]
