"""App Attest (report-only): Apple's server checks, the CBOR subset, and recording.

Attestations are built here with a test CA shaped like Apple's (P-384 root → P-384
intermediate → P-256 credential certificate carrying the nonce extension); production
pins Apple's real root, whose fingerprint is checked below.
"""

import base64
import contextlib
import hashlib
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Device
from app.services import app_attest, mobile_auth
from app.services.app_attest import AttestError
from tests.conftest import FakeMailer
from tests.test_mobile_auth import AppSession, app_client, sign_in

APP_ID = "ABCDE12345.app.eventfaces.ios"
NOW = datetime.now(UTC)


# --- a tiny CBOR encoder (tests only) ----------------------------------------------------------


def cbor(value: object) -> bytes:
    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError(n)

    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


# --- a test CA shaped like Apple's -----------------------------------------------------------


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject_key, issuer_key, subject: str, issuer: str, *, ca: bool, extra=None, days=(-1, 365)):  # type: ignore[no-untyped-def]
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + timedelta(days=days[0]))
        .not_valid_after(NOW + timedelta(days=days[1]))
    )
    if ca is not None:
        b = b.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    for ext in extra or []:
        b = b.add_extension(ext, critical=False)
    return b.sign(issuer_key, hashes.SHA384() if isinstance(issuer_key.curve, ec.SECP384R1) else hashes.SHA256())


@dataclass
class FakeCA:
    root: x509.Certificate
    root_key: ec.EllipticCurvePrivateKey
    inter: x509.Certificate
    inter_key: ec.EllipticCurvePrivateKey


def make_ca(*, intermediate_is_ca: bool = True) -> FakeCA:
    root_key, inter_key = ec.generate_private_key(ec.SECP384R1()), ec.generate_private_key(ec.SECP384R1())
    root = _cert(root_key, root_key, "Test App Attestation Root CA", "Test App Attestation Root CA", ca=True)
    inter = _cert(inter_key, root_key, "Test App Attestation CA 1", "Test App Attestation Root CA", ca=intermediate_is_ca)
    return FakeCA(root, root_key, inter, inter_key)


CA = make_ca()


def nonce_extension(nonce: bytes) -> x509.UnrecognizedExtension:
    octet = b"\x04" + bytes([len(nonce)]) + nonce
    tagged = b"\xa1" + bytes([len(octet)]) + octet
    return x509.UnrecognizedExtension(app_attest.NONCE_OID, b"\x30" + bytes([len(tagged)]) + tagged)


def point(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


@dataclass
class Attestation:
    raw: bytes
    key_id: bytes
    key: ec.EllipticCurvePrivateKey


def make_attestation(
    challenge: bytes,
    *,
    ca: FakeCA = CA,
    app_id: str = APP_ID,
    env: str = "development",
    counter: int = 0,
    credential_id: bytes | None = None,
    key_id_override: bytes | None = None,
    nonce_override: bytes | None = None,
    extensions: dict | None = None,
    leaf_days: tuple[int, int] = (-1, 365),
    fmt: str = "apple-appattest",
    with_root: bool = False,
) -> Attestation:
    key = ec.generate_private_key(ec.SECP256R1())
    key_id = hashlib.sha256(point(key)).digest()
    xy = key.public_key().public_numbers()
    cose = cbor({1: 2, 3: -7, -1: 1, -2: xy.x.to_bytes(32, "big"), -3: xy.y.to_bytes(32, "big")})
    flags = 0x40 | (0x80 if extensions is not None else 0)
    cred = credential_id if credential_id is not None else key_id
    auth = (
        hashlib.sha256(app_id.encode()).digest()
        + bytes([flags])
        + counter.to_bytes(4, "big")
        + app_attest.AAGUID[env]
        + len(cred).to_bytes(2, "big")
        + cred
        + cose
        + (cbor(extensions) if extensions is not None else b"")
    )
    nonce = nonce_override or hashlib.sha256(auth + hashlib.sha256(challenge).digest()).digest()
    leaf = _cert(key, ca.inter_key, "credential", "Test App Attestation CA 1", ca=None, extra=[nonce_extension(nonce)], days=leaf_days)
    x5c = [leaf.public_bytes(serialization.Encoding.DER), ca.inter.public_bytes(serialization.Encoding.DER)]
    if with_root:
        x5c.append(ca.root.public_bytes(serialization.Encoding.DER))
    raw = cbor({"fmt": fmt, "attStmt": {"x5c": x5c, "receipt": b"receipt"}, "authData": auth})
    return Attestation(raw, key_id_override or key_id, key)


def verify(att: Attestation, signed_challenge: bytes, **kw):  # type: ignore[no-untyped-def]
    args = {"challenge": signed_challenge, "key_id": att.key_id, "app_id": APP_ID, "environment": "development", "roots": [CA.root]}
    return app_attest.verify_attestation(att.raw, **(args | kw))


def make_assertion(key: ec.EllipticCurvePrivateKey, client_data: bytes, counter: int, *, app_id: str = APP_ID) -> bytes:
    auth = hashlib.sha256(app_id.encode()).digest() + b"\x00" + counter.to_bytes(4, "big")
    nonce = hashlib.sha256(auth + hashlib.sha256(client_data).digest()).digest()
    return cbor({"signature": key.sign(nonce, ec.ECDSA(hashes.SHA256())), "authenticatorData": auth})


# --- pinned root -------------------------------------------------------------------------------


def test_pinned_root_is_apples_app_attestation_root() -> None:
    root = x509.load_pem_x509_certificate(app_attest.APPLE_ROOT_PEM)
    assert root.fingerprint(hashes.SHA256()).hex() == "1cb9823ba28ba6ad2d33a006941de2ae4f513ef1d4e831b9f7e0fa7b6242c932"
    assert root.subject.rfc4514_string() == "ST=California,O=Apple Inc.,CN=Apple App Attestation Root CA"


def test_test_ca_attestation_is_refused_against_apples_root() -> None:
    challenge = b"c" * 32
    with pytest.raises(AttestError, match="chain_untrusted"):
        verify(make_attestation(challenge), challenge, roots=None)


# --- attestation -------------------------------------------------------------------------------


def test_valid_attestation_verifies_and_returns_the_key() -> None:
    challenge = b"challenge-bytes-0123456789abcdef"
    att = make_attestation(challenge, extensions={"apple_validation_category_01": 3, "apple_bundle_version_01": "1.0"})
    result = verify(att, challenge)
    assert base64.b64decode(result.public_key) == point(att.key)
    assert (result.counter, result.validation_category, result.bundle_version) == (0, 3, "1.0")


def test_attestation_with_the_root_in_the_chain_verifies() -> None:
    challenge = b"x" * 32
    verify(make_attestation(challenge, with_root=True), challenge)


@pytest.mark.parametrize(
    ("build", "check", "reason"),
    [
        ({}, {"challenge": b"another challenge"}, "nonce_mismatch"),
        ({"nonce_override": b"\x00" * 32}, {}, "nonce_mismatch"),
        ({"key_id_override": b"\x01" * 32}, {}, "key_id_mismatch"),
        ({"app_id": "ZZZZZ99999.app.eventfaces.ios"}, {}, "rp_id_mismatch"),
        ({}, {"app_id": "ABCDE12345.other.app"}, "rp_id_mismatch"),
        ({"counter": 1}, {}, "counter_not_zero"),
        ({"env": "development"}, {"environment": "production"}, "aaguid_mismatch"),
        ({"env": "production"}, {"environment": "development"}, "aaguid_mismatch"),
        ({"credential_id": b"\x02" * 32}, {}, "credential_id_mismatch"),
        ({"credential_id": b"\x02" * 16}, {}, "authdata_bad_credential"),
        ({"ca": make_ca()}, {}, "chain_untrusted"),
        ({"ca": make_ca(intermediate_is_ca=False), "trust_its_root": True}, {}, "chain_not_ca"),
        ({"leaf_days": (-10, -1)}, {}, "chain_expired"),
        ({"fmt": "packed"}, {}, "bad_format"),
        ({"extensions": {"apple_validation_category_01": 0}}, {}, "validation_category"),
        ({"extensions": {"apple_validation_category_01": 8}}, {}, "validation_category"),
    ],
)
def test_attestation_checks(build: dict, check: dict, reason: str) -> None:
    challenge = b"challenge-bytes-0123456789abcdef"
    build = dict(build)
    if build.pop("trust_its_root", False):
        check = check | {"roots": [build["ca"].root]}
    att = make_attestation(challenge, **build)
    with pytest.raises(AttestError) as e:
        verify(att, challenge, **check)
    assert e.value.reason == reason


def test_production_aaguid_verifies_in_production() -> None:
    challenge = b"p" * 32
    verify(make_attestation(challenge, env="production"), challenge, environment="production")


def test_chain_signed_by_an_impostor_with_the_same_names_is_refused() -> None:
    impostor = FakeCA(CA.root, ec.generate_private_key(ec.SECP384R1()), CA.inter, ec.generate_private_key(ec.SECP384R1()))
    challenge = b"i" * 32
    with pytest.raises(AttestError, match="chain_signature"):
        verify(make_attestation(challenge, ca=impostor), challenge)


def test_oversized_attestations_are_refused_before_parsing() -> None:
    with pytest.raises(AttestError, match="too_large"):
        app_attest.verify_attestation(
            b"\xa0" * (app_attest.MAX_ATTESTATION_BYTES + 1), challenge=b"", key_id=b"", app_id=APP_ID, environment="development"
        )


# --- CBOR ---------------------------------------------------------------------------------------


def test_cbor_decodes_the_subset_we_need() -> None:
    value = {"a": [1, -7, b"\x00\xff", "ü", True, False, None], 3: {-2: 2**40}}
    assert app_attest.cbor_decode(cbor(value)) == value


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"\x9f\x01\xff", "cbor_unsupported"),  # indefinite-length array
        (b"\xc1\x00", "cbor_unsupported"),  # tag
        (b"\xfb" + b"\x00" * 8, "cbor_unsupported"),  # float
        (b"\x5a\xff\xff\xff\xff", "cbor_truncated"),  # 4 GB byte string claimed
        (b"\x01\x02", "cbor_trailing_bytes"),
        (b"\x98\xff" + b"\x00" * 255, "cbor_too_large"),
        (b"\x81" * 20 + b"\x00", "cbor_too_deep"),
        (b"\xa2\x01\x00\x01\x00", "cbor_bad_map_key"),  # duplicate key
        (b"\xa1\x40\x00", "cbor_bad_map_key"),  # bytes as key
        (b"\x62\xc3\x28", "cbor_bad_text"),
        (b"", "cbor_truncated"),
    ],
)
def test_cbor_rejects_what_the_format_never_uses(raw: bytes, reason: str) -> None:
    with pytest.raises(AttestError) as e:
        app_attest.cbor_decode(raw)
    assert e.value.reason == reason


def test_hostile_input_only_ever_raises_attest_errors() -> None:
    rng = random.Random(1234)  # nosec B311 - fuzzing, not crypto
    challenge = b"f" * 32
    good = make_attestation(challenge).raw
    for _ in range(20000):
        data = bytearray(good)
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        if rng.random() < 0.2:
            data = data[: rng.randrange(len(data))]
        with contextlib.suppress(AttestError):  # anything else fails the test
            app_attest.verify_attestation(bytes(data), challenge=challenge, key_id=b"\x00" * 32, app_id=APP_ID, environment="development", roots=[CA.root])
    for _ in range(2000):
        with contextlib.suppress(AttestError):
            app_attest.cbor_decode(rng.randbytes(rng.randint(0, 64)))


# --- assertions ---------------------------------------------------------------------------------


def _key_b64(key: ec.EllipticCurvePrivateKey) -> str:
    return base64.b64encode(point(key)).decode()


def test_assertion_verifies_and_returns_its_counter() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    a = make_assertion(key, b"client data", 5)
    assert app_attest.verify_assertion(a, client_data=b"client data", public_key_b64=_key_b64(key), app_id=APP_ID, last_counter=4) == 5


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"client_data": b"other data"}, "assertion_signature"),
        ({"last_counter": 5}, "counter_replay"),
        ({"last_counter": 9}, "counter_replay"),
        ({"app_id": "ABCDE12345.other.app"}, "rp_id_mismatch"),
        ({"public_key_b64": _key_b64(ec.generate_private_key(ec.SECP256R1()))}, "assertion_signature"),
    ],
)
def test_assertion_checks(kw: dict, reason: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    a = make_assertion(key, b"client data", 5)
    args = {"client_data": b"client data", "public_key_b64": _key_b64(key), "app_id": APP_ID, "last_counter": 0}
    with pytest.raises(AttestError) as e:
        app_attest.verify_assertion(a, **(args | kw))
    assert e.value.reason == reason


# --- endpoints and recording (report-only) -----------------------------------------------------


@pytest.fixture
def attest_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "app_attest_app_id", APP_ID)
    monkeypatch.setattr(get_settings(), "app_attest_env", "development")
    monkeypatch.setattr(app_attest, "APPLE_ROOT_PEM", CA.root.public_bytes(serialization.Encoding.PEM))


def attest_device(s: AppSession, att_builder=make_attestation):  # type: ignore[no-untyped-def]
    r = s.client.post("/api/me/devices/current/attest/challenge")
    assert r.status_code == 200, r.text
    challenge = base64.b64decode(r.json()["challenge"])
    att = att_builder(challenge)
    r = s.client.post(
        "/api/me/devices/current/attest",
        json={"key_id": base64.b64encode(att.key_id).decode(), "attestation": base64.b64encode(att.raw).decode()},
    )
    assert r.status_code == 200, r.text
    return att, r.json()["status"]


def device_row(db: Session, s: AppSession) -> Device:
    db.expire_all()
    return db.scalars(select(Device).where(Device.id == s.device_id)).one()


def test_app_attest_is_off_until_configured(mailer: FakeMailer) -> None:
    s = sign_in(mailer, "off@example.com")
    assert s.client.post("/api/me/devices/current/attest/challenge").status_code == 404
    assert s.client.post("/api/me/devices/current/attest", json={"key_id": "A" * 43 + "=", "attestation": "AAAAAAAA"}).status_code == 404
    assert s.client.get("/api/app/config").json()["app_attest"] is False


def test_attestation_is_recorded_on_the_device(attest_on: None, mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "attest@example.com")
    assert s.client.get("/api/app/config").json()["app_attest"] is True
    att, status = attest_device(s)
    assert status == "verified"
    d = device_row(db, s)
    assert (d.attest_status, d.attest_reason, d.attest_counter) == ("verified", None, 0)
    assert d.attest_key_id == base64.b64encode(att.key_id).decode()
    assert base64.b64decode(d.attest_public_key or "") == point(att.key)


def test_a_failed_attestation_is_recorded_and_blocks_nothing(attest_on: None, mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "fails@example.com")
    _, status = attest_device(s, lambda c: make_attestation(c, ca=make_ca()))
    assert status == "failed"
    d = device_row(db, s)
    assert (d.attest_status, d.attest_reason, d.attest_key_id) == ("failed", "chain_untrusted", None)
    # Report-only: the session works and refreshes as before.
    assert s.client.get("/api/me").status_code == 200
    assert s.refresh_request().status_code == 200


def test_challenge_is_single_use_and_bound_to_the_device(attest_on: None, mailer: FakeMailer, db: Session) -> None:
    a, b = sign_in(mailer, "a-dev@example.com"), sign_in(mailer, "b-dev@example.com")
    challenge = base64.b64decode(a.client.post("/api/me/devices/current/attest/challenge").json()["challenge"])
    att = make_attestation(challenge)
    body = {"key_id": base64.b64encode(att.key_id).decode(), "attestation": base64.b64encode(att.raw).decode()}
    assert b.client.post("/api/me/devices/current/attest", json=body).json()["status"] == "failed"  # b has no challenge
    assert device_row(db, b).attest_reason == "no_challenge"
    assert a.client.post("/api/me/devices/current/attest", json=body).json()["status"] == "verified"
    assert a.client.post("/api/me/devices/current/attest", json=body).json()["status"] == "failed"  # used up
    assert device_row(db, a).attest_reason == "no_challenge"


def test_an_attested_key_cannot_be_reused_by_another_device(
    attest_on: None, mailer: FakeMailer, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apple: refuse a key that is already associated with another user. A real second
    attestation of the same key can't be built without the device, so the verifier is
    stubbed to accept it; the check after it must still refuse."""
    a, b = sign_in(mailer, "reuse-a@example.com"), sign_in(mailer, "reuse-b@example.com")
    att, _ = attest_device(a)
    accepted = app_attest.Attested(base64.b64encode(point(att.key)).decode(), 0, None, None)
    monkeypatch.setattr(app_attest, "verify_attestation", lambda *args, **kw: accepted)
    b.client.post("/api/me/devices/current/attest/challenge")
    r = b.client.post("/api/me/devices/current/attest", json={"key_id": base64.b64encode(att.key_id).decode(), "attestation": "AAAAAAAA"})
    assert r.json()["status"] == "failed"
    d = device_row(db, b)
    assert (d.attest_reason, d.attest_key_id) == ("key_reused", None)


def test_attest_endpoints_are_app_only(attest_on: None, make_user, login_as) -> None:  # type: ignore[no-untyped-def]
    web = login_as(make_user(email="web-attest@example.com"))
    assert web.post("/api/me/devices/current/attest/challenge").status_code == 400


def test_attest_challenges_are_rate_limited(attest_on: None, mailer: FakeMailer) -> None:
    s = sign_in(mailer, "limit@example.com")
    codes = [s.client.post("/api/me/devices/current/attest/challenge").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def _refresh_with_assertion(s: AppSession, key: ec.EllipticCurvePrivateKey | None, counter: int):  # type: ignore[no-untyped-def]
    ts = int(time.time())
    message = mobile_auth.refresh_message(s.refresh, uuid.UUID(s.device_id), ts)
    body = {"refresh_token": s.refresh, "device_id": s.device_id, "ts": ts, "signature": s.key.sign(s.refresh, s.device_id, ts)}
    if key is not None:
        body["assertion"] = base64.b64encode(make_assertion(key, message, counter)).decode()
    r = app_client().post("/api/mobile/auth/refresh", json=body)
    assert r.status_code == 200, r.text  # report-only: never blocks
    s.refresh = r.json()["refresh_token"]
    return r


def test_refresh_assertions_are_checked_and_recorded(attest_on: None, mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "assert@example.com")
    att, _ = attest_device(s)
    _refresh_with_assertion(s, att.key, 1)
    d = device_row(db, s)
    assert (d.assertion_status, d.attest_counter) == ("ok", 1)
    _refresh_with_assertion(s, att.key, 1)  # counter didn't move: a replayed assertion
    assert (device_row(db, s).assertion_status, device_row(db, s).assertion_reason) == ("failed", "counter_replay")
    _refresh_with_assertion(s, ec.generate_private_key(ec.SECP256R1()), 7)  # another key
    assert device_row(db, s).assertion_reason == "assertion_signature"
    _refresh_with_assertion(s, None, 0)
    assert device_row(db, s).assertion_status == "missing"
    _refresh_with_assertion(s, att.key, 2)
    d = device_row(db, s)
    assert (d.assertion_status, d.attest_counter) == ("ok", 2)


def test_assertion_is_bound_to_the_refresh_it_came_with(attest_on: None, mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "bound@example.com")
    att, _ = attest_device(s)
    ts = int(time.time())
    other = mobile_auth.refresh_message("some-other-token-xxxxxxxxxx", uuid.UUID(s.device_id), ts)
    body = {
        "refresh_token": s.refresh,
        "device_id": s.device_id,
        "ts": ts,
        "signature": s.key.sign(s.refresh, s.device_id, ts),
        "assertion": base64.b64encode(make_assertion(att.key, other, 1)).decode(),
    }
    assert app_client().post("/api/mobile/auth/refresh", json=body).status_code == 200
    assert device_row(db, s).assertion_reason == "assertion_signature"


def test_attest_report_counts_results_without_identifying_anyone(attest_on: None, mailer: FakeMailer) -> None:
    from app.cli import attest_report

    ok, bad = sign_in(mailer, "report-ok@example.com"), sign_in(mailer, "report-bad@example.com")
    sign_in(mailer, "report-none@example.com")
    att, _ = attest_device(ok)
    attest_device(bad, lambda c: make_attestation(c, ca=make_ca()))
    _refresh_with_assertion(ok, att.key, 1)
    rows = attest_report()
    assert ("attestation", "verified", "-", 1) in rows
    assert ("attestation", "failed", "chain_untrusted", 1) in rows
    assert ("attestation", "none", "-", 1) in rows
    assert ("assertion", "ok", "-", 1) in rows
    assert all(isinstance(r, str) for row in rows for r in row[:3])  # codes only, never emails or ids
