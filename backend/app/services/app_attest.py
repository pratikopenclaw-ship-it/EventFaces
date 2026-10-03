"""App Attest (Apple DeviceCheck): evidence that requests come from a genuine EventFaces
build on a genuine Apple device.

**Report-only** (APP_ATTEST_MODE=report): results are recorded on the device row and
logged as reason codes, and never block a request. Enforcing comes after the reported
results show that real installs pass (see IOS_QA_REPORT.md, Phase 7).

Flow:
1. The app asks for a one-time challenge (Redis, 5 min, single use, bound to the device).
2. It attests a fresh App Attest key over SHA-256(challenge) and posts the attestation;
   `verify_attestation` runs Apple's server checks and stores the key.
3. Every device-signed refresh may carry an assertion over the refresh message (already
   time-bound and single-use); `verify_assertion` checks it and the counter.

Apple's steps: developer.apple.com/documentation/devicecheck/validating-apps-that-connect-to-your-server
The CBOR decoder below covers exactly what the format uses (definite lengths, no tags or
floats); anything else is rejected. It replaces a third-party CBOR dependency.
"""

import base64
import hashlib
import itertools
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, UTC

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import utcnow
from app.models import Device

log = logging.getLogger(__name__)

# Apple App Attestation Root CA (https://www.apple.com/certificateauthority/private/),
# valid 2020-03-18 to 2045-03-15. SHA-256 fingerprint pinned in tests.
APPLE_ROOT_PEM = b"""-----BEGIN CERTIFICATE-----
MIICITCCAaegAwIBAgIQC/O+DvHN0uD7jG5yH2IXmDAKBggqhkjOPQQDAzBSMSYw
JAYDVQQDDB1BcHBsZSBBcHAgQXR0ZXN0YXRpb24gUm9vdCBDQTETMBEGA1UECgwK
QXBwbGUgSW5jLjETMBEGA1UECAwKQ2FsaWZvcm5pYTAeFw0yMDAzMTgxODMyNTNa
Fw00NTAzMTUwMDAwMDBaMFIxJjAkBgNVBAMMHUFwcGxlIEFwcCBBdHRlc3RhdGlv
biBSb290IENBMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQIDApDYWxpZm9y
bmlhMHYwEAYHKoZIzj0CAQYFK4EEACIDYgAERTHhmLW07ATaFQIEVwTtT4dyctdh
NbJhFs/Ii2FdCgAHGbpphY3+d8qjuDngIN3WVhQUBHAoMeQ/cLiP1sOUtgjqK9au
Yen1mMEvRq9Sk3Jm5X8U62H+xTD3FE9TgS41o0IwQDAPBgNVHRMBAf8EBTADAQH/
MB0GA1UdDgQWBBSskRBTM72+aEH/pwyp5frq5eWKoTAOBgNVHQ8BAf8EBAMCAQYw
CgYIKoZIzj0EAwMDaAAwZQIwQgFGnByvsiVbpTKwSga0kP0e8EeDS4+sQmTvb7vn
53O5+FRXgeLhpJ06ysC5PrOyAjEAp5U4xDgEgllF7En3VcE3iexZZtKeYnpqtijV
oyFraWVIyd/dganmrduC1bmTBGwD
-----END CERTIFICATE-----
"""

NONCE_OID = x509.ObjectIdentifier("1.2.840.113635.100.8.2")
AAGUID = {"development": b"appattestdevelop", "production": b"appattest" + b"\x00" * 7}
MAX_ATTESTATION_BYTES = 16 * 1024
MAX_ASSERTION_BYTES = 1024


class AttestError(ValueError):
    """`reason` is a short code that is safe to log and store (no key material)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --- CBOR (RFC 8949), the subset App Attest uses ---------------------------------------------


def cbor_decode(data: bytes) -> object:
    value, end = _cbor_item(data, 0, depth=0)
    if end != len(data):
        raise AttestError("cbor_trailing_bytes")
    return value


def cbor_decode_prefix(data: bytes, pos: int) -> tuple[object, int]:
    """Decode one item starting at `pos`; returns it and the offset after it."""
    return _cbor_item(data, pos, depth=0)


def _cbor_item(data: bytes, pos: int, depth: int) -> tuple[object, int]:
    if depth > 8:
        raise AttestError("cbor_too_deep")
    if pos >= len(data):
        raise AttestError("cbor_truncated")
    major, info = data[pos] >> 5, data[pos] & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        n = 1 << (info - 24)
        if pos + n > len(data):
            raise AttestError("cbor_truncated")
        arg = int.from_bytes(data[pos : pos + n], "big")
        pos += n
    else:  # 28-30 reserved, 31 = indefinite length: not used by App Attest
        raise AttestError("cbor_unsupported")
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise AttestError("cbor_truncated")
        raw = data[pos : pos + arg]
        if major == 2:
            return bytes(raw), pos + arg
        try:
            return raw.decode("utf-8"), pos + arg
        except UnicodeDecodeError:
            raise AttestError("cbor_bad_text") from None
    if major in (4, 5):
        if arg > 64:  # nothing in the format comes close; caps work on hostile input
            raise AttestError("cbor_too_large")
        if major == 4:
            items = []
            for _ in range(arg):
                item, pos = _cbor_item(data, pos, depth + 1)
                items.append(item)
            return items, pos
        out: dict = {}
        for _ in range(arg):
            key, pos = _cbor_item(data, pos, depth + 1)
            if not isinstance(key, int | str) or key in out:
                raise AttestError("cbor_bad_map_key")
            out[key], pos = _cbor_item(data, pos, depth + 1)
        return out, pos
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    raise AttestError("cbor_unsupported")  # tags (6), floats and other simple values


# --- Authenticator data ------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthData:
    rp_id_hash: bytes
    flags: int
    counter: int
    aaguid: bytes | None = None
    credential_id: bytes | None = None
    extensions: dict | None = None


def parse_auth_data(raw: bytes, *, attested: bool) -> AuthData:
    if len(raw) < 37:
        raise AttestError("authdata_short")
    rp, flags, counter = raw[:32], raw[32], int.from_bytes(raw[33:37], "big")
    if not attested:
        return AuthData(rp, flags, counter)
    if not flags & 0x40 or len(raw) < 55:  # AT: attested credential data present
        raise AttestError("authdata_no_credential")
    aaguid = raw[37:53]
    cred_len = int.from_bytes(raw[53:55], "big")
    cred_end = 55 + cred_len
    if cred_len != 32 or len(raw) < cred_end:
        raise AttestError("authdata_bad_credential")
    _cose_key, pos = cbor_decode_prefix(raw, cred_end)
    extensions: dict | None = None
    if flags & 0x80:  # ED: extensions follow the key
        decoded, pos = cbor_decode_prefix(raw, pos)
        if not isinstance(decoded, dict):
            raise AttestError("authdata_bad_extensions")
        extensions = decoded
    if pos != len(raw):
        raise AttestError("authdata_trailing_bytes")
    return AuthData(rp, flags, counter, aaguid, raw[55:cred_end], extensions)


# --- Attestation ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Attested:
    public_key: str  # base64 X9.62 uncompressed point
    counter: int
    validation_category: int | None
    bundle_version: str | None


def _der_len(data: bytes, pos: int) -> tuple[int, int]:
    if pos >= len(data):
        raise AttestError("nonce_ext_malformed")
    first = data[pos]
    if first < 0x80:
        return first, pos + 1
    n = first & 0x7F
    if n == 0 or n > 2 or pos + 1 + n > len(data):
        raise AttestError("nonce_ext_malformed")
    return int.from_bytes(data[pos + 1 : pos + 1 + n], "big"), pos + 1 + n


def _nonce_from_extension(value: bytes) -> bytes:
    """SEQUENCE { [1] EXPLICIT OCTET STRING nonce }, exactly."""
    out = value
    for tag in (0x30, 0xA1, 0x04):
        if not out or out[0] != tag:
            raise AttestError("nonce_ext_malformed")
        length, start = _der_len(out, 1)
        if start + length != len(out):
            raise AttestError("nonce_ext_malformed")
        out = out[start:]
    return out


def _check_chain(chain: list[bytes], roots: list[x509.Certificate], now: datetime) -> x509.Certificate:
    """Leaf → intermediate → pinned root: signatures, names, validity, CA constraints."""
    if not 2 <= len(chain) <= 3 or not all(isinstance(c, bytes) for c in chain):
        raise AttestError("chain_shape")
    try:
        certs = [x509.load_der_x509_certificate(c) for c in chain]
    except ValueError:
        raise AttestError("chain_unparseable") from None
    for cert in certs:
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise AttestError("chain_expired")
    for issuer in certs[1:]:
        try:
            bc = issuer.extensions.get_extension_for_class(x509.BasicConstraints).value
        except x509.ExtensionNotFound:
            raise AttestError("chain_not_ca") from None
        if not bc.ca:
            raise AttestError("chain_not_ca")
    for child, issuer in itertools.pairwise(certs):
        try:
            child.verify_directly_issued_by(issuer)
        except (ValueError, TypeError, InvalidSignature):
            raise AttestError("chain_signature") from None
    top = certs[-1]
    for root in roots:
        if top == root:  # Apple's x5c ends at the intermediate; tolerate the root too
            return certs[0]
        try:
            top.verify_directly_issued_by(root)
            return certs[0]
        except (ValueError, TypeError, InvalidSignature):
            continue
    raise AttestError("chain_untrusted")


def verify_attestation(
    attestation: bytes,
    *,
    challenge: bytes,
    key_id: bytes,
    app_id: str,
    environment: str,
    roots: list[x509.Certificate] | None = None,
    now: datetime | None = None,
) -> Attested:
    """Apple's attestation checks, in their order. Raises AttestError(reason) only:
    `cryptography` parses certificates lazily, so a malformed field can surface as a
    library exception deep inside a check."""
    try:
        return _verify_attestation(attestation, challenge, key_id, app_id, environment, roots, now)
    except AttestError:
        raise
    except Exception:
        raise AttestError("malformed") from None


def _verify_attestation(
    attestation: bytes,
    challenge: bytes,
    key_id: bytes,
    app_id: str,
    environment: str,
    roots: list[x509.Certificate] | None,
    now: datetime | None,
) -> Attested:
    if len(attestation) > MAX_ATTESTATION_BYTES:
        raise AttestError("too_large")
    obj = cbor_decode(attestation)
    if not isinstance(obj, dict) or obj.get("fmt") != "apple-appattest":
        raise AttestError("bad_format")
    stmt, auth_raw = obj.get("attStmt"), obj.get("authData")
    if not isinstance(stmt, dict) or not isinstance(auth_raw, bytes) or not isinstance(stmt.get("x5c"), list):
        raise AttestError("bad_format")
    # 1. Certificate chain up to Apple's App Attest root.
    roots = roots if roots is not None else [x509.load_pem_x509_certificate(APPLE_ROOT_PEM)]
    leaf = _check_chain(stmt["x5c"], roots, now or datetime.now(UTC))
    # 2-4. nonce = SHA256(authData || SHA256(challenge)) must equal the leaf's extension.
    nonce = hashlib.sha256(auth_raw + hashlib.sha256(challenge).digest()).digest()
    try:
        ext = leaf.extensions.get_extension_for_oid(NONCE_OID).value
    except x509.ExtensionNotFound:
        raise AttestError("nonce_ext_missing") from None
    if not isinstance(ext, x509.UnrecognizedExtension) or _nonce_from_extension(ext.value) != nonce:
        raise AttestError("nonce_mismatch")
    # 5. The key id is the SHA256 of the leaf's public key (uncompressed point).
    leaf_key = leaf.public_key()
    if not isinstance(leaf_key, ec.EllipticCurvePublicKey) or not isinstance(leaf_key.curve, ec.SECP256R1):
        raise AttestError("leaf_key_type")
    point = leaf_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    if hashlib.sha256(point).digest() != key_id:
        raise AttestError("key_id_mismatch")
    auth = parse_auth_data(auth_raw, attested=True)
    # 6. RP ID = SHA256(Team ID + "." + bundle id).
    if auth.rp_id_hash != hashlib.sha256(app_id.encode()).digest():
        raise AttestError("rp_id_mismatch")
    # 7. A fresh key has never signed anything.
    if auth.counter != 0:
        raise AttestError("counter_not_zero")
    # 8. Development keys never pass in production (and vice versa).
    if auth.aaguid != AAGUID[environment]:
        raise AttestError("aaguid_mismatch")
    # 9. The credential id is the key id.
    if auth.credential_id != key_id:
        raise AttestError("credential_id_mismatch")
    # 10-11. Validation category and bundle version (newer OS versions add them): recorded.
    ext_map = auth.extensions or {}
    category = ext_map.get("apple_validation_category_01")
    version = ext_map.get("apple_bundle_version_01")
    if category is not None and (not isinstance(category, int) or category in (0, 7, 8, 9)):
        raise AttestError("validation_category")
    return Attested(
        public_key=base64.b64encode(point).decode(),
        counter=0,
        validation_category=category,
        bundle_version=version if isinstance(version, str) else None,
    )


# --- Assertions -----------------------------------------------------------------------------


def verify_assertion(assertion: bytes, *, client_data: bytes, public_key_b64: str, app_id: str, last_counter: int) -> int:
    """Checks one assertion over `client_data`; returns its counter. Raises AttestError.

    The caller binds `client_data` to a server challenge: for refreshes it is the signed
    refresh message, which carries the time and is accepted once."""
    if len(assertion) > MAX_ASSERTION_BYTES:
        raise AttestError("too_large")
    obj = cbor_decode(assertion)
    if not isinstance(obj, dict) or not isinstance(obj.get("signature"), bytes) or not isinstance(obj.get("authenticatorData"), bytes):
        raise AttestError("bad_format")
    auth_raw = obj["authenticatorData"]
    nonce = hashlib.sha256(auth_raw + hashlib.sha256(client_data).digest()).digest()
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(public_key_b64))
        key.verify(obj["signature"], nonce, ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        raise AttestError("assertion_signature") from None
    auth = parse_auth_data(auth_raw, attested=False)
    if auth.rp_id_hash != hashlib.sha256(app_id.encode()).digest():
        raise AttestError("rp_id_mismatch")
    if auth.counter <= last_counter:
        raise AttestError("counter_replay")
    return auth.counter


# --- Recording (report-only) -----------------------------------------------------------------

CHALLENGE_TTL_SECONDS = 300


def enabled() -> bool:
    return bool(get_settings().app_attest_app_id)


def _challenge_key(device_id: uuid.UUID) -> str:
    return f"attest-challenge:{device_id}"


def issue_challenge(device: Device) -> bytes:
    """A one-time challenge for this device (a new one replaces the old)."""
    challenge = secrets.token_bytes(32)
    get_redis().set(_challenge_key(device.id), challenge.hex(), ex=CHALLENGE_TTL_SECONDS)
    return challenge


def record_attestation(db: Session, device: Device, key_id_b64: str, attestation_b64: str) -> str:
    """Verifies and records an attestation; returns "verified" or "failed". Never raises
    for a bad attestation (report-only)."""
    s = get_settings()
    stored = get_redis().getdel(_challenge_key(device.id))  # single use, even on failure
    try:
        if stored is None:
            raise AttestError("no_challenge")
        challenge = bytes.fromhex(stored)
        try:
            key_id = base64.b64decode(key_id_b64, validate=True)
            attestation = base64.b64decode(attestation_b64, validate=True)
        except ValueError:
            raise AttestError("bad_encoding") from None
        attested = verify_attestation(
            attestation, challenge=challenge, key_id=key_id, app_id=s.app_attest_app_id, environment=s.app_attest_env
        )
        # One attested key belongs to one device row (Apple: refuse keys already in use).
        taken = db.scalar(select(Device.id).where(Device.attest_key_id == key_id_b64, Device.id != device.id))
        if taken is not None:
            raise AttestError("key_reused")
    except AttestError as e:
        device.attest_status, device.attest_reason = "failed", e.reason
        device.attest_checked_at = utcnow()
        log.warning("app attest: attestation failed (%s)", e.reason)
        return "failed"
    device.attest_key_id, device.attest_public_key, device.attest_counter = key_id_b64, attested.public_key, attested.counter
    device.attest_status, device.attest_reason = "verified", None
    device.attest_checked_at = utcnow()
    device.assertion_status = device.assertion_reason = None
    return "verified"


def record_refresh_assertion(device: Device, assertion_b64: str | None, refresh_message: bytes) -> None:
    """Checks the assertion that came with a device-signed refresh (report-only)."""
    if device.attest_status != "verified" or not device.attest_public_key:
        return  # nothing to check against yet
    if not assertion_b64:
        device.assertion_status, device.assertion_reason = "missing", None
        log.warning("app attest: refresh without an assertion")
        return
    try:
        try:
            assertion = base64.b64decode(assertion_b64, validate=True)
        except ValueError:
            raise AttestError("bad_encoding") from None
        counter = verify_assertion(
            assertion,
            client_data=refresh_message,
            public_key_b64=device.attest_public_key,
            app_id=get_settings().app_attest_app_id,
            last_counter=device.attest_counter or 0,
        )
    except AttestError as e:
        device.assertion_status, device.assertion_reason = "failed", e.reason
        log.warning("app attest: assertion failed (%s)", e.reason)
        return
    device.attest_counter = counter
    device.assertion_status, device.assertion_reason = "ok", None
