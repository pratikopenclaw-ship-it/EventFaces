#!/usr/bin/env python3
"""Every user-facing string in the app must be in Localizable.xcstrings with a German
translation. Scans Features/ and App/ (UI code) for string literals that read like UI
text: they start with a capital letter or contain a space. Interpolations become %@
(the String Catalog key format).

    scripts/check-strings.py            # check (exit 1 on gaps)
    scripts/check-strings.py --list     # print the extracted keys
"""

import json
import pathlib
import re
import sys

IOS = pathlib.Path(__file__).resolve().parents[1]
CATALOG = IOS / "EventFaces" / "Resources" / "Localizable.xcstrings"
UI_DIRS = [IOS / "EventFaces" / "Features", IOS / "EventFaces" / "App", IOS / "EventFaces" / "Design"]
SKIP_FILES = {"AppConfig.swift", "Palette.swift", "EventFacesApp.swift"}
# Literals that are not UI text (asset names, notification names, ...).
NOT_UI = {"Bg", "Ignored a link the app doesn't handle"}  # asset name; log line
LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def keys() -> set[str]:
    out: set[str] = set()
    for d in UI_DIRS:
        for f in d.rglob("*.swift"):
            if f.name in SKIP_FILES:
                continue
            for line in f.read_text().splitlines():
                if line.strip().startswith("//"):
                    continue  # comments and doc comments
                code = line
                if "accessibilityIdentifier" in code or "systemImage" in code and "Label(" not in code:
                    pass
                for m in LITERAL.finditer(code):
                    s = m.group(1)
                    before = code[: m.start()]
                    if re.search(r"(accessibilityIdentifier|systemName|systemImage|forKey|named|arguments\.contains|Image)\($", before.rstrip()):
                        continue
                    if re.search(r"(systemImage|symbol|identifier|verbatim):\s*$", before.rstrip()):
                        continue
                    key = re.sub(r"\\\([^)]*\)", "%@", s)
                    if key in NOT_UI or not any(ch.isalpha() for ch in key.replace("%@", "")):
                        continue  # not UI text, or punctuation/numbers only (nothing to translate)
                    if key[0].isupper() or " " in key:
                        out.add(key)
    return out


def translated(loc: dict) -> bool:
    """A plain translation, or plural variations that are all translated."""
    if "stringUnit" in loc:
        return loc["stringUnit"].get("state") == "translated"
    forms = loc.get("variations", {}).get("plural", {})
    return bool(forms) and "other" in forms and all(f.get("stringUnit", {}).get("state") == "translated" for f in forms.values())


def main() -> int:
    found = keys()
    if "--list" in sys.argv:
        print("\n".join(sorted(found)))
        return 0
    catalog = json.loads(CATALOG.read_text())["strings"] if CATALOG.exists() else {}
    # Interpolations become %@ (strings) or %lld (integers) in catalog keys.
    normalized = {k.replace("%lld", "%@") for k in catalog}
    missing = sorted(k for k in found if k not in catalog and k not in normalized)
    untranslated = sorted(k for k, v in catalog.items() if not translated(v.get("localizations", {}).get("de", {})))
    for k in missing:
        print(f"missing from catalog: {k!r}")
    for k in untranslated:
        print(f"no German translation: {k!r}")
    print(f"{len(found)} UI strings, {len(catalog)} catalog entries")
    return 1 if missing or untranslated else 0


if __name__ == "__main__":
    sys.exit(main())
