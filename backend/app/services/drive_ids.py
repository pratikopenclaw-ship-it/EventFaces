import re

_ID = r"[A-Za-z0-9_-]{10,200}"
_URL_PATTERNS = [
    re.compile(rf"/folders/({_ID})"),
    re.compile(rf"[?&]id=({_ID})"),
]
_BARE_ID = re.compile(rf"^{_ID}$")


def parse_drive_folder_id(value: str) -> str | None:
    """Accept a Drive folder URL (…/drive/folders/<id>, ?id=<id>) or a bare ID."""
    value = value.strip()
    if _BARE_ID.match(value):
        return value
    if "drive.google.com" not in value:
        return None
    for pattern in _URL_PATTERNS:
        if m := pattern.search(value):
            return m.group(1)
    return None
