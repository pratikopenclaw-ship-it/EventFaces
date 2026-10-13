"""Billing with the fake (TEST MODE) provider: checkout, confirmations, fulfilment,
subscriptions, plan limits and account deletion.

Security properties:
- only a verified provider confirmation (signed, fresh, applied once, right amount) marks
  an order paid; the customer's browser can't;
- only published test cards are accepted, and card numbers are never stored or echoed;
- customers only ever see their own orders.
"""

import json
import time
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import (
    DriveSyncRun,
    Event,
    EventMember,
    MemberRole,
    MemberStatus,
    Order,
    OrderKind,
    OrderStatus,
    Photo,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.services import drive
from app.services.billing import orders
from app.services.billing.plans import PLANS, vat_part
from app.services.billing.provider import SIGNATURE_HEADER, get_provider
from tests.conftest import PASSWORD
from tests.helpers import FakeDrive, solid_jpeg

GOOD = "4242 4242 4242 4242"
DECLINED = "4000 0000 0000 0002"
CARD = {"expiry": "12/30", "cvc": "123"}

MakeUser = Callable[..., User]
LoginAs = Callable[[User], TestClient]


def buy(client: TestClient, plan: str = "event_s", card: str = GOOD, **body: object) -> dict:
    """Checkout → hosted test page → pay. Returns the pay response."""
    r = client.post("/api/billing/checkout", json={"plan": plan, "event_name": "Our Wedding", **body})
    assert r.status_code == 200, r.text
    session = r.json()["checkout_url"].rsplit("/", 1)[-1]
    assert client.get(f"/api/billing/test-checkout/{session}").status_code == 200
    r = client.post(f"/api/billing/test-checkout/{session}/pay", json={"card_number": card, **CARD})
    assert r.status_code == 200, r.text
    return r.json() | {"session": session}


def webhook(client: TestClient, payload: dict, *, ts: float | None = None, secret: str | None = None) -> object:
    raw = json.dumps(payload).encode()
    provider = get_provider() if secret is None else type(get_provider())(secret)
    headers = provider.sign(raw, ts) | {"content-type": "application/json"}
    return client.post("/api/billing/webhook/fake", content=raw, headers=headers)


def completed(order: Order, event_id: str = "evt_test_1", amount: int | None = None) -> dict:
    return {
        "id": event_id,
        "type": "checkout.completed",
        "data": {"session": order.provider_ref, "amount_total": order.amount_cents if amount is None else amount, "currency": "eur"},
    }


def pending_order(client: TestClient, db: Session, plan: str = "event_s") -> Order:
    r = client.post("/api/billing/checkout", json={"plan": plan, "event_name": "Gala"})
    assert r.status_code == 200, r.text
    db.expire_all()
    order = db.get(Order, r.json()["order_id"])
    assert order is not None
    return order


# --- price list --------------------------------------------------------------------------


def test_price_list_is_public_and_matches_the_plans(client: TestClient) -> None:
    body = client.get("/api/billing/plans").json()
    assert body["currency"] == "EUR" and body["vat_rate"] == 19 and body["vat_included"] is True
    assert body["test_mode"] is True and body["example_prices"] is True
    assert {p["key"]: p["price_cents"] for p in body["plans"]} == {k: p.price_cents for k, p in PLANS.items()}
    pro = next(p for p in body["plans"] if p["key"] == "pro")
    assert pro["kind"] == "subscription" and pro["events_per_period"] == 5


def test_vat_is_the_part_contained_in_the_gross_price() -> None:
    assert vat_part(4_900) == 782  # 49.00 incl. 19% → 7.82 VAT
    assert vat_part(11_900) == 1_900


# --- one-off purchase ----------------------------------------------------------------------


def test_buying_an_event_creates_it_and_makes_the_buyer_its_organizer(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    buyer = make_user("buyer@example.com")
    client = login_as(buyer)
    result = buy(client, "event_s", event_date="2026-12-24")
    assert result["outcome"] == "paid"
    order = result["order"]
    assert order["status"] == "paid" and order["amount_cents"] == 4_900 and order["vat_cents"] == 782
    db.expire_all()
    event = db.get(Event, order["event_id"])
    assert event is not None and event.name == "Our Wedding" and str(event.date) == "2026-12-24"
    assert (event.plan, event.max_attendees, event.max_photos) == ("event_s", 100, 500)
    assert db.get(User, buyer.id).role == UserRole.organizer  # type: ignore[union-attr]
    m = db.get(EventMember, (event.id, buyer.id))
    assert m is not None and m.role == MemberRole.organizer and m.status == MemberStatus.approved
    assert client.get(f"/api/events/{event.id}/admin").status_code == 200
    usage = client.get(f"/api/events/{event.id}/usage").json()
    assert usage == {"plan": "event_s", "plan_name": "Event S", "max_attendees": 100, "max_photos": 500, "attendees": 0, "photos": 0}


def test_new_organizers_accept_the_organizer_terms_before_managing(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    buyer = make_user("fresh@example.com")
    buyer.organizer_terms_version = None
    db.commit()
    client = login_as(buyer)
    event_id = buy(client)["order"]["event_id"]
    r = client.get(f"/api/events/{event_id}/admin")
    assert r.status_code == 403 and r.headers.get("x-required-action") == "accept-organizer-terms"


def test_a_declined_card_keeps_the_order_payable(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    client = login_as(make_user("declined@example.com"))
    result = buy(client, card=DECLINED)
    assert result["outcome"] == "failed"
    assert result["order"]["status"] == "pending" and result["order"]["failure_code"] == "card_declined"
    assert db.scalar(select(Event)) is None
    r = client.post(f"/api/billing/test-checkout/{result['session']}/pay", json={"card_number": GOOD, **CARD})
    assert r.json()["outcome"] == "paid" and r.json()["order"]["failure_code"] is None


def test_real_card_numbers_are_refused_and_never_echoed(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    client = login_as(make_user("realcard@example.com"))
    order = pending_order(client, db)
    real = "5555555555554444"
    r = client.post(f"/api/billing/test-checkout/{order.provider_ref}/pay", json={"card_number": real, **CARD})
    assert r.status_code == 422 and "test card" in r.text and real not in r.text
    # A malformed one fails validation: still no echo of what was typed.
    r = client.post(f"/api/billing/test-checkout/{order.provider_ref}/pay", json={"card_number": "4111-1111-1111-1111", **CARD})
    assert r.status_code == 422 and "4111" not in r.text
    db.expire_all()
    assert db.get(Order, order.id).status == OrderStatus.pending  # type: ignore[union-attr]
    assert real not in json.dumps([str(v) for v in db.execute(select(Order.__table__)).all()])


def test_validation_errors_never_echo_what_was_sent(client: TestClient) -> None:
    secret = "tiny" + "pw"
    r = client.post("/api/auth/signup", json={"accept_terms": True, "email": "x@example.com", "password": secret})
    assert r.status_code == 422 and secret not in r.text
    assert all(set(e) <= {"type", "loc", "msg"} for e in r.json()["detail"])


def test_checkout_needs_an_event_name_for_event_plans(make_user: MakeUser, login_as: LoginAs) -> None:
    client = login_as(make_user("noname@example.com"))
    assert client.post("/api/billing/checkout", json={"plan": "event_m"}).status_code == 422
    assert client.post("/api/billing/checkout", json={"plan": "platinum", "event_name": "x"}).status_code == 422


def test_unverified_users_cannot_buy(make_user: MakeUser, login_as: LoginAs) -> None:
    client = login_as(make_user("unverified@example.com", verified=False))
    assert client.post("/api/billing/checkout", json={"plan": "event_s", "event_name": "x"}).status_code == 403


# --- only verified confirmations count -----------------------------------------------------


def test_customers_only_see_and_pay_their_own_orders(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    owner = login_as(make_user("owner@example.com"))
    order = pending_order(owner, db)
    other = login_as(make_user("other@example.com"))
    assert other.get(f"/api/billing/orders/{order.id}").status_code == 404
    assert other.get(f"/api/billing/test-checkout/{order.provider_ref}").status_code == 404
    r = other.post(f"/api/billing/test-checkout/{order.provider_ref}/pay", json={"card_number": GOOD, **CARD})
    assert r.status_code == 404
    assert other.get("/api/billing/overview").json()["orders"] == []
    db.expire_all()
    assert db.get(Order, order.id).status == OrderStatus.pending  # type: ignore[union-attr]


def test_a_signed_webhook_marks_the_order_paid_once(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    order = pending_order(login_as(make_user("hook@example.com")), db)
    anonymous = TestClient(__import__("app.main", fromlist=["app"]).app)
    r = webhook(anonymous, completed(order))
    assert r.status_code == 200 and r.json() == {"status": "paid"}
    # The same event again (a retry or a replay), and a second event for the same checkout.
    assert webhook(anonymous, completed(order)).json() == {"status": "duplicate"}
    assert webhook(anonymous, completed(order, "evt_test_2")).json() == {"status": "duplicate"}
    db.expire_all()
    assert db.scalars(select(Event)).all().__len__() == 1


@pytest.mark.parametrize(
    "case",
    ["wrong_secret", "stale", "future", "unsigned", "tampered_body"],
)
def test_forged_or_replayed_confirmations_are_refused(case: str, make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    order = pending_order(login_as(make_user(f"forge-{case}@example.com")), db)
    anonymous = TestClient(__import__("app.main", fromlist=["app"]).app)
    payload = completed(order)
    raw = json.dumps(payload).encode()
    if case == "wrong_secret":
        r = webhook(anonymous, payload, secret="guessed-" + "x" * 32)  # not the configured secret
    elif case == "stale":
        r = webhook(anonymous, payload, ts=time.time() - 3600)
    elif case == "future":
        r = webhook(anonymous, payload, ts=time.time() + 3600)
    elif case == "unsigned":
        r = anonymous.post("/api/billing/webhook/fake", content=raw, headers={"content-type": "application/json"})
    else:
        headers = get_provider().sign(raw) | {"content-type": "application/json"}
        r = anonymous.post("/api/billing/webhook/fake", content=raw.replace(b"evt_test_1", b"evt_test_9"), headers=headers)
    assert r.status_code == 400  # type: ignore[attr-defined]
    db.expire_all()
    assert db.get(Order, order.id).status == OrderStatus.pending  # type: ignore[union-attr]
    assert db.scalar(select(Event)) is None


def test_a_confirmation_for_the_wrong_amount_never_fulfils(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    order = pending_order(login_as(make_user("amount@example.com")), db)
    anonymous = TestClient(__import__("app.main", fromlist=["app"]).app)
    assert webhook(anonymous, completed(order, amount=100)).json() == {"status": "ignored"}
    db.expire_all()
    assert db.get(Order, order.id).status == OrderStatus.pending  # type: ignore[union-attr]
    assert db.scalar(select(Event)) is None


def test_the_webhook_is_csrf_exempt_only_without_session_cookies(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    client = login_as(make_user("csrf@example.com"))
    order = pending_order(client, db)
    raw = json.dumps(completed(order)).encode()
    headers = get_provider().sign(raw) | {"content-type": "application/json"}
    # A logged-in browser (cookies) without the CSRF header: the normal CSRF rule applies.
    client.headers.pop("X-CSRF-Token", None)
    assert client.post("/api/billing/webhook/fake", content=raw, headers=headers).status_code == 403
    assert SIGNATURE_HEADER in headers


def test_the_webhook_refuses_oversized_bodies() -> None:
    anonymous = TestClient(__import__("app.main", fromlist=["app"]).app)
    raw = b"{" + b" " * 70_000 + b"}"
    r = anonymous.post("/api/billing/webhook/fake", content=raw, headers=get_provider().sign(raw) | {"content-type": "application/json"})
    assert r.status_code == 413


# --- subscriptions -------------------------------------------------------------------------


def test_subscription_allowance_and_cancellation(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    user = make_user("pro@example.com")
    client = login_as(user)
    result = buy(client, "pro", event_name="First of five")
    assert result["outcome"] == "paid" and result["order"]["kind"] == "subscription"
    overview = client.get("/api/billing/overview").json()
    sub = overview["subscription"]
    assert sub["status"] == "active" and sub["events_included"] == 5 and sub["events_used"] == 1
    for i in range(4):
        r = client.post("/api/billing/subscription/events", json={"name": f"Event {i}"})
        assert r.status_code == 200, r.text
    r = client.post("/api/billing/subscription/events", json={"name": "One too many"})
    assert r.status_code == 409 and "used up" in r.text
    db.expire_all()
    events = db.scalars(select(Event)).all()
    assert len(events) == 5 and all((e.plan, e.max_attendees, e.max_photos) == ("pro", 500, 3_000) for e in events)
    allowance = db.scalars(select(Order).where(Order.kind == OrderKind.allowance)).all()
    assert len(allowance) == 4 and all(o.amount_cents == 0 and o.status == OrderStatus.paid for o in allowance)
    # A second subscription while one runs: refused.
    assert client.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 409
    canceled = client.post("/api/billing/subscription/cancel").json()
    assert canceled["canceled_at"] is not None and canceled["status"] == "active"  # until the period ends


def test_maintenance_renews_or_ends_subscriptions_and_cancels_abandoned_checkouts(make_user: MakeUser, db: Session) -> None:
    now = utcnow()
    keep, leave = make_user("keep@example.com"), make_user("leave@example.com")
    renew = Subscription(user_id=keep.id, plan="pro", status=SubscriptionStatus.active, current_period_start=now - timedelta(days=31), current_period_end=now - timedelta(hours=1))
    end = Subscription(user_id=leave.id, plan="pro", status=SubscriptionStatus.active, current_period_start=now - timedelta(days=31), current_period_end=now - timedelta(hours=1), canceled_at=now - timedelta(days=3))
    stale = Order(user_id=keep.id, plan="event_s", kind=OrderKind.one_off, amount_cents=4_900, currency="EUR", vat_rate=19, status=OrderStatus.pending, provider="fake", provider_ref="fcs_stale", created_at=now - timedelta(hours=25))
    fresh = Order(user_id=keep.id, plan="event_s", kind=OrderKind.one_off, amount_cents=4_900, currency="EUR", vat_rate=19, status=OrderStatus.pending, provider="fake", provider_ref="fcs_fresh")
    db.add_all([renew, end, stale, fresh])
    db.commit()
    assert orders.run_maintenance(db) == {"abandoned": 1, "expired": 1, "renewed": 1}
    db.expire_all()
    assert renew.status == SubscriptionStatus.active and renew.current_period_end > utcnow()
    assert end.status == SubscriptionStatus.expired
    assert stale.status == OrderStatus.canceled and fresh.status == OrderStatus.pending
    renewal = db.scalars(select(Order).where(Order.subscription_id == renew.id)).all()
    assert len(renewal) == 1 and renewal[0].status == OrderStatus.paid and renewal[0].amount_cents == 19_900


# --- plan limits ---------------------------------------------------------------------------


def test_a_full_event_admits_no_new_attendees(make_user: MakeUser, login_as: LoginAs, make_event: Callable[..., Event], add_member: Callable[..., EventMember]) -> None:
    event = make_event("Small", max_attendees=2, plan="event_s")
    first, second, third = (make_user(f"g{i}@example.com") for i in range(3))
    for u in (first, second):
        assert login_as(u).post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 200
    r = login_as(third).post("/api/join", json={"slug": event.slug, "code": event.access_code})
    assert r.status_code == 403 and "full" in r.text
    # Members already in can come back; organizers don't count.
    assert login_as(first).post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 200
    add_member(event, make_user("o@example.com", UserRole.organizer), role=MemberRole.organizer)
    # A revoked attendee frees the seat.
    add_member(event, make_user("gone@example.com"), status=MemberStatus.revoked)
    assert login_as(third).post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 403


def test_invites_respect_the_attendee_limit(make_user: MakeUser, login_as: LoginAs, make_event: Callable[..., Event], add_member: Callable[..., EventMember], db: Session) -> None:
    from app.models import Invite, InviteStatus, JoinMode
    from app.services.invites import accept

    event = make_event("Invite only", join_mode=JoinMode.invite, max_attendees=1, plan="event_s")
    add_member(event, make_user("in@example.com"))
    late = make_user("late@example.com")
    invite = Invite(event_id=event.id, email=late.email, token_hash="x" * 64, status=InviteStatus.pending, expires_at=utcnow() + timedelta(days=1))
    db.add(invite)
    db.commit()
    with pytest.raises(Exception) as exc:
        accept(db, invite, event, late)
    assert getattr(exc.value, "status_code", None) == 403
    db.rollback()
    assert db.get(EventMember, (event.id, late.id)) is None


def test_guest_uploads_stop_at_the_photo_limit(make_user: MakeUser, login_as: LoginAs, make_event: Callable[..., Event], add_member: Callable[..., EventMember], db: Session) -> None:
    from app.models import IndexStatus, PhotoSource, PhotoStatus

    event = make_event("Tiny", guest_upload_enabled=True, max_photos=1, plan="event_s")
    guest = make_user("up@example.com")
    add_member(event, guest)
    db.add(Photo(event_id=event.id, source=PhotoSource.drive, drive_file_id="d1", original_filename="a.jpg", status=PhotoStatus.published, index_status=IndexStatus.indexed))
    db.commit()
    r = login_as(guest).post(f"/api/events/{event.id}/uploads", json={"filename": "b.jpg", "content_type": "image/jpeg", "size": 1000})
    assert r.status_code == 409 and "photo limit" in r.text


def test_drive_import_stops_at_the_photo_limit_and_reports_it(make_user: MakeUser, login_as: LoginAs, make_event: Callable[..., Event], add_member: Callable[..., EventMember], db: Session) -> None:
    folder = "1PlanLimitFolderAAAAA"
    event = make_event("Capped", drive_folder_id=folder, max_photos=2, plan="event_s")
    org = make_user("cap@example.com", UserRole.organizer)
    add_member(event, org, role=MemberRole.organizer)
    files = {f"f{i}": (f"{i}.jpg", solid_jpeg()) for i in range(5)}
    drive.set_drive_client(FakeDrive({folder: files}))
    client = login_as(org)
    assert client.post(f"/api/events/{event.id}/sync").status_code == 202
    db.expire_all()
    assert len(db.scalars(select(Photo).where(Photo.event_id == event.id)).all()) == 2
    run = db.scalars(select(DriveSyncRun).where(DriveSyncRun.event_id == event.id)).one()
    assert run.files_over_limit == 3
    # A re-sync doesn't import more, and the already-imported files aren't counted as cut off.
    assert client.post(f"/api/events/{event.id}/sync").status_code == 202
    db.expire_all()
    assert len(db.scalars(select(Photo).where(Photo.event_id == event.id)).all()) == 2
    last = db.scalars(select(DriveSyncRun).where(DriveSyncRun.event_id == event.id).order_by(DriveSyncRun.created_at.desc())).first()
    assert last is not None and last.files_over_limit == 3


def test_events_without_a_plan_have_no_limits(make_user: MakeUser, login_as: LoginAs, make_event: Callable[..., Event]) -> None:
    event = make_event("Admin-made")
    for i in range(3):
        assert login_as(make_user(f"free{i}@example.com")).post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 200


# --- account deletion ----------------------------------------------------------------------


def test_deleting_an_account_keeps_orders_but_ends_the_subscription(make_user: MakeUser, login_as: LoginAs, db: Session) -> None:
    user = make_user("leaver@example.com")
    client = login_as(user)
    buy(client, "pro", event_name="Last party")
    assert client.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code == 200
    db.expire_all()
    order = db.scalars(select(Order).where(Order.kind == OrderKind.subscription)).one()
    assert order.user_id is None and order.status == OrderStatus.paid  # kept for the books, unlinked
    sub = db.scalars(select(Subscription)).one()
    assert sub.user_id is None and sub.status == SubscriptionStatus.expired
    assert orders.run_maintenance(db)["renewed"] == 0


# --- add-on pricing -----------------------------------------------------------------------


from app.models import AddonKind
from app.services.billing.addon_prices import ADDON_PRICES, addon_price_cents


def test_addon_price_lookup_matches_the_table():
    assert addon_price_cents(AddonKind.human_edit) == ADDON_PRICES[AddonKind.human_edit]
    assert ADDON_PRICES[AddonKind.human_edit] > 0
