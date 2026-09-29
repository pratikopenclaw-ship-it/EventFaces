"""Role-based authorization for event management."""

from app.models import MemberRole, UserRole


def test_only_super_admin_creates_events(make_user, login_as) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    organizer = login_as(make_user("org@example.com", UserRole.organizer))
    attendee = login_as(make_user("att@example.com"))

    body = {"name": "Launch Night", "drive_folder": "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp"}
    assert attendee.post("/api/events", json=body).status_code == 403
    assert organizer.post("/api/events", json=body).status_code == 403

    r = admin.post("/api/events", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["drive_folder_id"] == "1AbCdEfGhIjKlMnOp"
    assert len(data["access_code"]) == 8


def test_invalid_drive_folder_rejected(make_user, login_as) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    r = admin.post("/api/events", json={"name": "X", "drive_folder": "https://evil.example.com/folders/abc"})
    assert r.status_code == 422


def test_organizer_manages_only_own_events(make_user, login_as, make_event, add_member) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    own = make_event("Own Event")
    other = make_event("Other Event")
    add_member(own, org_user, role=MemberRole.organizer)
    org = login_as(org_user)

    assert org.patch(f"/api/events/{own.id}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert org.get(f"/api/events/{own.id}/admin").status_code == 200
    assert org.get(f"/api/events/{own.id}/members").status_code == 200

    assert org.patch(f"/api/events/{other.id}", json={"name": "Hijack"}).status_code == 403
    assert org.get(f"/api/events/{other.id}/admin").status_code == 403
    assert org.get(f"/api/events/{other.id}/members").status_code == 403
    assert org.post(f"/api/events/{other.id}/access-code/rotate").status_code == 403

    listed = {e["id"] for e in org.get("/api/events").json()}
    assert listed == {str(own.id)}


def test_organizer_cannot_delete_or_assign_organizers(make_user, login_as, make_event, add_member) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    make_user("friend@example.com")
    event = make_event()
    add_member(event, org_user, role=MemberRole.organizer)
    org = login_as(org_user)

    assert org.delete(f"/api/events/{event.id}").status_code == 403
    assert org.post(f"/api/events/{event.id}/organizers", json={"email": "friend@example.com"}).status_code == 403


def test_super_admin_assigns_organizer(make_user, login_as, make_event) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    future_org = make_user("new-org@example.com")
    event = make_event()

    r = admin.post(f"/api/events/{event.id}/organizers", json={"email": future_org.email})
    assert r.status_code == 201
    assert r.json()["role"] == "organizer"

    org = login_as(future_org)
    assert org.get("/api/me").json()["role"] == "organizer"
    assert org.patch(f"/api/events/{event.id}", json={"description": "hi"}).status_code == 200


def test_super_admin_sees_and_edits_everything(make_user, login_as, make_event) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    e1, e2 = make_event("One"), make_event("Two")
    assert {e["id"] for e in admin.get("/api/events").json()} == {str(e1.id), str(e2.id)}
    assert admin.patch(f"/api/events/{e2.id}", json={"guest_upload_enabled": True}).status_code == 200
    assert admin.delete(f"/api/events/{e1.id}").status_code == 204
    assert admin.get(f"/api/events/{e1.id}").status_code == 404


def test_attendee_sees_public_view_only(make_user, login_as, make_event, add_member) -> None:
    user = make_user("att@example.com")
    event = make_event()
    add_member(event, user)
    att = login_as(user)

    r = att.get(f"/api/events/{event.id}")
    assert r.status_code == 200
    assert "access_code" not in r.json()
    assert att.get(f"/api/events/{event.id}/admin").status_code == 403
    assert att.get(f"/api/events/{event.id}/members").status_code == 403


def test_organizer_cannot_revoke_other_organizer(make_user, login_as, make_event, add_member) -> None:
    a = make_user("a@example.com", UserRole.organizer)
    b = make_user("b@example.com", UserRole.organizer)
    event = make_event()
    add_member(event, a, role=MemberRole.organizer)
    add_member(event, b, role=MemberRole.organizer)
    r = login_as(a).patch(f"/api/events/{event.id}/members/{b.id}", json={"status": "revoked"})
    assert r.status_code == 403
