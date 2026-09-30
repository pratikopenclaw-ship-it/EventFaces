"""Per-process cap on face-model work (selfie searches, removal-request references).

Face analysis takes seconds of CPU and is serialized per process, so requests beyond the
cap would only queue, each holding its selfie bodies (up to 3 × 10 MB) in memory while
latency grows without bound (SEC-039). A request takes a slot *before* reading its body;
if none frees up within SEARCH_QUEUE_WAIT_SECONDS it gets 503 + Retry-After instead.
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, status

from app.core.config import get_settings

RETRY_AFTER_SECONDS = 10
BUSY = HTTPException(
    status.HTTP_503_SERVICE_UNAVAILABLE,
    "Lots of people are searching right now. Please try again in a few seconds.",
    headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
)

_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None


def _semaphore() -> threading.BoundedSemaphore:
    global _slots  # noqa: PLW0603 - one semaphore per process, sized from settings on first use
    with _lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(get_settings().search_max_concurrent)
        return _slots


def reset() -> None:
    """Forget the semaphore so the next use re-reads the setting (tests)."""
    global _slots  # noqa: PLW0603
    with _lock:
        _slots = None


def try_acquire_now() -> bool:
    return _semaphore().acquire(blocking=False)


def release() -> None:
    _semaphore().release()


async def _acquire(wait_seconds: float) -> bool:
    # A threading semaphore (not asyncio's) so it works across event loops and with work
    # that runs in the threadpool; polled so waiting never blocks the event loop.
    deadline = time.monotonic() + wait_seconds
    while True:
        if try_acquire_now():
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)


@asynccontextmanager
async def face_slot() -> AsyncIterator[None]:
    """Hold one face-work slot for the block, or raise 503 if the process is saturated."""
    if not await _acquire(get_settings().search_queue_wait_seconds):
        raise BUSY
    try:
        yield
    finally:
        release()
