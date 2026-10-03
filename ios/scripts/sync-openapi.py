#!/usr/bin/env python3
"""backend/openapi.json -> ios/EventFaces/Core/API/openapi.json, adapted for
swift-openapi-generator.

The generator skips OpenAPI 3.1 nullable fields (`anyOf: [T, {"type": "null"}]`), which
silently dropped e.g. `accent_color` and `given_at` from the Swift types. Each such field
becomes plain `T` and is removed from its parent's `required` list: a Swift optional
decodes both a missing key and `null`, so nothing the API sends is lost.

    scripts/sync-openapi.py          # write the iOS copy
    scripts/sync-openapi.py --check  # exit 1 if the copy is stale
"""

import json
import pathlib
import sys

IOS = pathlib.Path(__file__).resolve().parents[1]
SOURCE = IOS.parent / "backend" / "openapi.json"
TARGET = IOS / "EventFaces" / "Core" / "API" / "openapi.json"
NULL = {"type": "null"}


def unnull(node: object) -> tuple[object, bool]:
    """(node without null branches, whether this node itself was nullable)."""
    if isinstance(node, list):
        return [unnull(x)[0] for x in node], False
    if not isinstance(node, dict):
        return node, False
    nullable = False
    out = {}
    for key, value in node.items():
        out[key] = unnull(value)[0]
    branches = out.get("anyOf")
    if isinstance(branches, list) and NULL in branches:
        rest = [b for b in branches if b != NULL]
        nullable = True
        out.pop("anyOf")
        if len(rest) == 1:
            out = {**rest[0], **{k: v for k, v in out.items() if k in ("title", "description", "default")}}
        else:
            out["anyOf"] = rest
    if isinstance(out.get("properties"), dict):
        optional = []
        for name, prop in list(node.get("properties", {}).items()):
            if isinstance(prop, dict) and NULL in prop.get("anyOf", []):
                optional.append(name)
        if optional and isinstance(out.get("required"), list):
            out["required"] = [r for r in out["required"] if r not in optional]
            if not out["required"]:
                out.pop("required")
    if out.get("in") in ("query", "header", "path") and isinstance(node.get("schema"), dict) and NULL in node["schema"].get("anyOf", []):
        out["required"] = False if out.get("in") != "path" else out.get("required", True)
    return out, nullable


def render() -> str:
    return json.dumps(unnull(json.loads(SOURCE.read_text()))[0], indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            print("ios openapi.json is stale: run ios/scripts/bootstrap.sh")
            return 1
        return 0
    TARGET.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
