"""addon_orders.start_checkout: buyer authorization (organizers for any event photo,
attendees only for their own viewable published photo) and basic input validation."""

import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import (
    AddonKind,
    AddonOrder,
    AddonOrderStatus,
    Event,
    EventMember,
    IndexStatus,
    MemberRole,
    Photo,
    PhotoSource,
    PhotoStatus,
    SearchGrant,
    User,
    UserRole,
)
from app.services.billing import addon_orders
from app.services.billing.addon_prices import ADDON_PRICES

MakeUser = Callable[..., User]
MakeEvent = Callable[..., Event]
AddMember = Callable[..., EventMember]


def _photo(db: Session, event: Event, **kw) -> Photo:
    p = Photo(
        id=uuid.uuid4(),
        event_id=event.id,
        source=kw.pop("source", PhotoSource.drive),
        drive_file_id=f"f-{uuid.uuid4().hex[:8]}",
        original_filename="p.jpg",
        status=kw.pop("status", PhotoStatus.published),
        index_status=IndexStatus.indexed,
        **kw,
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def event(make_event: MakeEvent) -> Event:
    return make_event()


@pytest.fixture
def organizer(make_user: MakeUser, event: Event, add_member: AddMember) -> User:
    user = make_user("organizer@example.com", role=UserRole.organizer)
    add_member(event, user, role=MemberRole.organizer)
    return user


@pytest.fixture
def attendee_member(make_user: MakeUser, event: Event, add_member: AddMember) -> User:
    user = make_user("attendee@example.com", role=UserRole.attendee)
    add_member(event, user, role=MemberRole.attendee)
    return user


@pytest.fixture
def photo(db: Session, event: Event) -> Photo:
    return _photo(db, event)


def test_organizer_can_buy_addon_for_any_event_photo(db: Session, organizer: User, event: Event, photo: Photo) -> None:
    order, url = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    assert order.status == AddonOrderStatus.pending
    assert order.amount_cents == ADDON_PRICES[AddonKind.human_edit]
    assert order.event_id == event.id
    assert order.photo_ids == [photo.id]
    assert url.startswith("/checkout/test/")


def test_attendee_can_buy_addon_only_for_their_own_viewable_photo(
    db: Session, attendee_member: User, event: Event
) -> None:
    own_photo = _photo(db, event, uploaded_by=attendee_member.id)
    someone_elses_photo = _photo(db, event)

    order, _ = addon_orders.start_checkout(db, event, attendee_member, AddonKind.human_edit, [own_photo.id])
    assert order.photo_ids == [own_photo.id]

    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, attendee_member, AddonKind.human_edit, [someone_elses_photo.id])
    assert exc.value.status_code == 403


def test_attendee_can_buy_addon_for_a_matched_photo_via_search_grant(
    db: Session, attendee_member: User, event: Event
) -> None:
    matched_photo = _photo(db, event)
    db.add(
        SearchGrant(
            user_id=attendee_member.id,
            photo_id=matched_photo.id,
            event_id=event.id,
            similarity=0.9,
            expires_at=utcnow() + timedelta(days=30),
        )
    )
    db.commit()

    order, _ = addon_orders.start_checkout(db, event, attendee_member, AddonKind.human_edit, [matched_photo.id])
    assert order.photo_ids == [matched_photo.id]


def test_photo_ids_from_another_event_are_rejected_not_silently_dropped(
    db: Session, organizer: User, event: Event, make_event: MakeEvent
) -> None:
    other_event = make_event("Other Event")
    other_event_photo = _photo(db, other_event)

    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [other_event_photo.id])
    assert exc.value.status_code == 422


def test_empty_photo_ids_is_rejected(db: Session, organizer: User, event: Event) -> None:
    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [])
    assert exc.value.status_code == 422


from app.services.billing.provider import get_provider


def test_confirmation_marks_order_paid(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    result = addon_orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    assert result.outcome == "paid"
    db.refresh(order)
    assert order.status == AddonOrderStatus.paid
    assert order.paid_at is not None


def test_replayed_confirmation_is_a_duplicate_not_a_double_fulfil(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    conf = provider.parse_confirmation(raw, headers)
    first = addon_orders.apply_confirmation(db, provider.name, conf)
    second = addon_orders.apply_confirmation(db, provider.name, conf)
    assert first.outcome == "paid"
    assert second.outcome == "duplicate"


def test_confirmation_for_unknown_session_is_ignored_not_an_error(db: Session):
    provider = get_provider()
    from app.services.billing.provider import Confirmation

    conf = Confirmation(event_id="evt_nope", type="checkout.completed", session_ref="fcs_doesnotexist", amount_cents=100, currency="EUR")
    result = addon_orders.apply_confirmation(db, provider.name, conf)
    assert result.outcome == "ignored"


def test_failed_payment_sets_failure_code_not_paid(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4000000000000002")  # published "card_declined" test card
    result = addon_orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    assert result.outcome == "failed"
    db.refresh(order)
    assert order.status == AddonOrderStatus.pending
    assert order.failure_code == "card_declined"


def test_addon_checkout_route_then_pay_marks_paid(login_as, organizer, event, photo):
    client = login_as(organizer)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
    )
    assert resp.status_code == 200
    session_ref = resp.json()["checkout_url"].rsplit("/", 1)[-1]

    get_resp = client.get(f"/api/billing/addon-checkout/{session_ref}")
    assert get_resp.status_code == 200
    assert get_resp.json()["test_cards"]

    pay_resp = client.post(
        f"/api/billing/addon-checkout/{session_ref}/pay",
        json={"card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"},
    )
    assert pay_resp.status_code == 200
    assert pay_resp.json()["outcome"] == "paid"
    assert pay_resp.json()["order"]["status"] == "paid"


def test_addon_checkout_rejects_non_member(login_as, make_user, event, photo):
    stranger = make_user("stranger@example.com")
    client = login_as(stranger)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
    )
    assert resp.status_code == 403


def test_webhook_routes_addon_confirmation_to_addon_order(login_as, db, organizer, event, photo):
    client = login_as(organizer)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
    )
    session_ref = resp.json()["checkout_url"].rsplit("/", 1)[-1]
    order = db.scalar(select(AddonOrder).where(AddonOrder.provider_ref == session_ref))

    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    anonymous = TestClient(__import__("app.main", fromlist=["app"]).app)
    webhook_resp = anonymous.post("/api/billing/webhook/fake", content=raw, headers=headers)
    assert webhook_resp.status_code == 200
    assert webhook_resp.json()["status"] == "paid"
    db.refresh(order)
    assert order.status == AddonOrderStatus.paid
