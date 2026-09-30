"""Overflow queue for selfie searches: "we'll notify you when your photos are ready".

When every face-work slot is busy (SEC-039), a validated search is queued here instead
of being turned away. Privacy invariants:

- Selfies live **only in this process's memory** (a bounded in-process queue), never in
  Redis, on disk or in storage, and are dropped as soon as the job has run. A restart
  therefore loses queued searches; their status then reads "expired" after
  SEARCH_QUEUE_TTL_SECONDS and the user is asked to search again.
- Redis holds only the job *status* per user+event (state, timestamps, match count,
  rejection reason): no image, no embedding.
- Authorization and consent are re-checked when the job runs (the user may have been
  revoked, withdrawn consent or deleted their account while it waited).
- The queue is bounded by job count and by bytes; notification emails carry a link only.
"""

import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core import face_slots
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.email import Mail, get_mailer
from app.core.redis import get_redis
from app.core.security import utcnow
from app.models import Event, User
from app.services.membership import can_access
from app.services.search import FACE_CONSENT_VERSION, SelfieRejected, run_search

log = logging.getLogger(__name__)

STATUS_TTL_SECONDS = 24 * 3600  # status only; the selfies themselves are gone long before
# Each process heart-beats while it can run queued jobs. A queued job whose owner stopped
# beating (restart, crash) is reported "expired" within HEARTBEAT_TTL, not after the TTL.
BOOT_ID = uuid.uuid4().hex
HEARTBEAT_TTL_SECONDS = 30
HEARTBEAT_EVERY_SECONDS = 10


class QueueFull(Exception):
    pass


class AlreadyQueued(Exception):
    pass


@dataclass
class Job:
    user_id: uuid.UUID
    event_id: uuid.UUID
    shots: list[tuple[str, bytes]]
    size: int = field(init=False)

    def __post_init__(self) -> None:
        self.size = sum(len(data) for _, data in self.shots)


_lock = threading.Lock()
_queue: "queue.Queue[Job]" = queue.Queue()
_bytes = 0  # selfie bytes currently held by queued + running jobs
_inflight = 0
_stop = threading.Event()
_worker: threading.Thread | None = None


def now() -> datetime:
    return utcnow()


def _key(user_id: uuid.UUID, event_id: uuid.UUID) -> str:
    return f"searchjob:{user_id}:{event_id}"


def _claim_key(user_id: uuid.UUID, event_id: uuid.UUID) -> str:
    return f"searchjob:{user_id}:{event_id}:claim"  # same prefix: forget_user() removes it too


def _alive_key(boot_id: str) -> str:
    return f"searchqueue:alive:{boot_id}"


def _heartbeat() -> None:
    get_redis().set(_alive_key(BOOT_ID), "1", ex=HEARTBEAT_TTL_SECONDS)


def _set_status(user_id: uuid.UUID, event_id: uuid.UUID, state: str, **extra: Any) -> None:
    record = {"state": state, "updated_at": now().isoformat(), **extra}
    get_redis().set(_key(user_id, event_id), json.dumps(record), ex=STATUS_TTL_SECONDS)


def _decode(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"state": "none"}
    try:
        record: dict[str, Any] = json.loads(raw)
    except ValueError:
        return {"state": "none"}
    if record.get("state") == "queued":
        queued_at = datetime.fromisoformat(record["queued_at"])
        owner = record.get("owner")
        if (now() - queued_at).total_seconds() > get_settings().search_queue_ttl_seconds or (
            owner and not get_redis().exists(_alive_key(owner))
        ):
            record["state"] = "expired"  # lost (e.g. server restart): ask the user to search again
    return record


def get_status(user_id: uuid.UUID, event_id: uuid.UUID) -> dict[str, Any]:
    return _decode(get_redis().get(_key(user_id, event_id)))


def states_for(user_id: uuid.UUID, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not event_ids:
        return {}
    raws = get_redis().mget([_key(user_id, e) for e in event_ids])
    return {e: _decode(raw)["state"] for e, raw in zip(event_ids, raws, strict=True) if raw}


def forget_user(user_id: uuid.UUID) -> None:
    r = get_redis()
    for key in r.scan_iter(f"searchjob:{user_id}:*"):
        r.delete(key)


def check_can_queue(user_id: uuid.UUID, event_id: uuid.UUID) -> None:
    """Cheap checks before the request body is read."""
    if get_settings().search_overflow_queue_size <= 0 or _queue.qsize() >= get_settings().search_overflow_queue_size:
        raise QueueFull
    if get_status(user_id, event_id)["state"] == "queued":
        raise AlreadyQueued


def enqueue(user_id: uuid.UUID, event_id: uuid.UUID, shots: list[tuple[str, bytes]]) -> None:
    global _bytes  # noqa: PLW0603 - process-wide byte budget
    s = get_settings()
    job = Job(user_id, event_id, shots)
    with _lock:
        if _queue.qsize() >= s.search_overflow_queue_size or _bytes + job.size > s.search_queue_max_bytes:
            raise QueueFull
        # Atomic across API processes: one queued search per user+event.
        r = get_redis()
        if not r.set(_claim_key(user_id, event_id), BOOT_ID, nx=True, ex=s.search_queue_ttl_seconds):
            if get_status(user_id, event_id)["state"] == "queued":
                raise AlreadyQueued
            r.set(_claim_key(user_id, event_id), BOOT_ID, ex=s.search_queue_ttl_seconds)  # stale claim (lost job)
        _heartbeat()
        _bytes += job.size
        _set_status(user_id, event_id, "queued", queued_at=now().isoformat(), owner=BOOT_ID)
        _queue.put(job)
    _ensure_worker()


def pending() -> int:
    with _lock:
        return _queue.qsize() + _inflight


def _ensure_worker() -> None:
    global _worker  # noqa: PLW0603 - one worker thread per process
    with _lock:
        if _worker is None or not _worker.is_alive():
            _stop.clear()
            _worker = threading.Thread(target=_work, name="search-queue", daemon=True)
            _worker.start()


def _work() -> None:
    global _inflight, _bytes  # noqa: PLW0603
    last_beat = 0.0
    while not _stop.is_set():
        if time.monotonic() - last_beat > HEARTBEAT_EVERY_SECONDS:
            try:
                _heartbeat()
                last_beat = time.monotonic()
            except Exception:  # Redis blip: the next loop retries
                log.warning("Search queue heartbeat failed")
        try:
            job = _queue.get(timeout=0.2)
        except queue.Empty:
            continue
        with _lock:
            _inflight += 1
        try:
            # Share the per-process face-work cap with synchronous searches.
            while not face_slots.acquire_blocking(timeout=0.2):
                if _stop.is_set():
                    return
            try:
                process(job)
            finally:
                face_slots.release()
        except Exception:  # never let one job kill the worker
            log.exception("Queued search failed")
            _set_status(job.user_id, job.event_id, "expired")
        finally:
            with _lock:
                _inflight -= 1
                _bytes -= job.size
            job.shots = []  # drop the selfies
            try:
                get_redis().delete(_claim_key(job.user_id, job.event_id))
            except Exception:  # the claim expires with the TTL anyway
                log.warning("Could not release queued-search claim")


def process(job: Job) -> None:
    """Run one queued search with fresh authorization and consent checks."""
    frontend = get_settings().frontend_url
    with SessionLocal() as db:
        user = db.get(User, job.user_id)
        event = db.get(Event, job.event_id)
        if user is None or user.deleted_at is not None:
            return  # account gone: nothing to record or notify
        if (
            event is None
            or not user.is_verified
            or user.face_consent_version != FACE_CONSENT_VERSION
            or not can_access(db, event, user)
        ):
            _set_status(job.user_id, job.event_id, "cancelled")
            return
        email, event_name = user.email, event.name
        db.commit()  # no pooled connection held during face work (SEC-038)
        link = f"{frontend}/events/{event.id}"
        try:
            outcome = run_search(db, user, event, job.shots)
        except SelfieRejected as e:
            _set_status(job.user_id, job.event_id, "rejected", message=e.message, shot=e.shot, code=e.code)
            _notify(email, f"We couldn't use your selfie for {event_name}",
                    f"{e.message}\n\nPlease try again: {link}\n")
            return
        finally:
            job.shots = []
        _set_status(job.user_id, job.event_id, "done", match_count=len(outcome.matches))
        # A link only: no photos, no counts (the mailbox may not be private).
        _notify(email, f"Your photos from {event_name} are ready",
                f"Your photo search for {event_name} is complete.\n\nSee your results: {link}\n")


def _notify(to: str, subject: str, body: str) -> None:
    try:
        get_mailer().send(Mail(to=to, subject=subject, body=body))
    except Exception:  # a failed email must not lose the result: it's on the event page
        log.warning("Search notification email failed")


def reset() -> None:
    """Drop every queued job (what a process restart does). Tests only."""
    global _queue, _bytes  # noqa: PLW0603
    with _lock:
        _queue = queue.Queue()
        _bytes = 0


def stop() -> None:
    """Stop the worker and drop queued jobs (tests / shutdown)."""
    global _worker  # noqa: PLW0603
    _stop.set()
    if _worker is not None:
        _worker.join(timeout=10)
    _worker = None
    reset()
