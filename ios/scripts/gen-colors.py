#!/usr/bin/env python3
"""design/tokens.json -> EventFaces/Resources/Assets.xcassets/Colors/*.colorset (light + dark).

The iOS app and the web app share one token file; run this after editing it
(bootstrap.sh does). Names are PascalCase: text-muted -> TextMuted, accent -> Accent.
DesignTokensTests checks the catalog against tokens.json, so a stale catalog fails CI."""

import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOKENS = json.loads((ROOT / "design" / "tokens.json").read_text())
CATALOG = ROOT / "ios" / "EventFaces" / "Resources" / "Assets.xcassets"
COLORS = CATALOG / "Colors"


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-"))


def components(hex_value: str) -> dict[str, str]:
    h = hex_value.lstrip("#")
    return {"alpha": "1.000", "red": f"0x{h[0:2].upper()}", "green": f"0x{h[2:4].upper()}", "blue": f"0x{h[4:6].upper()}"}


def colorset(light: str, dark: str) -> dict:
    entry = lambda value, dark_mode: {  # noqa: E731
        "color": {"color-space": "srgb", "components": components(value)},
        "idiom": "universal",
        **({"appearances": [{"appearance": "luminosity", "value": "dark"}]} if dark_mode else {}),
    }
    return {"colors": [entry(light, False), entry(dark, True)], "info": {"author": "xcode", "version": 1}}


def main() -> None:
    CATALOG.mkdir(parents=True, exist_ok=True)
    (CATALOG / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    shutil.rmtree(COLORS, ignore_errors=True)
    COLORS.mkdir()
    (COLORS / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}, "properties": {"provides-namespace": False}}, indent=2) + "\n")
    for name in TOKENS["light"]:
        d = COLORS / f"{pascal(name)}.colorset"
        d.mkdir()
        (d / "Contents.json").write_text(json.dumps(colorset(TOKENS["light"][name], TOKENS["dark"][name]), indent=2) + "\n")
    print(f"{len(TOKENS['light'])} colour sets -> {COLORS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
