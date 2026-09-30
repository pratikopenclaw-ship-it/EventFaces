"""Keep bearer secrets that travel in URLs out of access logs.

Download, invite, removal and reset tokens are in URL paths or query strings (they
come from emailed links); whoever can read the logs must not be able to use them.
"""

import logging
import re

_PATTERNS = [
    re.compile(r"(/api/downloads/)[^/?\s\"]+"),
    re.compile(r"(/api/invites/)(?!accept\b|register\b)[^/?\s\"]+"),
    re.compile(r"(/api/removal-requests/)(?!event/)[^/?\s\"]+"),
    re.compile(r"(/invite/)[^/?\s\"]+"),
    re.compile(r"(/removal/)[^/?\s\"]+"),
    re.compile(r"([?&]token=)[^&\s\"]+"),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1[redacted]", text)
    return text


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        record.msg = redact(str(record.msg))
        return True


def install() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokens) for f in access.filters):
        access.addFilter(RedactTokens())
