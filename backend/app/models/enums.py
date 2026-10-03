import enum


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    organizer = "organizer"
    attendee = "attendee"


class TokenKind(str, enum.Enum):
    verify_email = "verify_email"
    reset_password = "reset_password"  # noqa: S105  # nosec B105 - token type name, not a password
    refresh = "refresh"
    invite = "invite"


class JoinMode(str, enum.Enum):
    code = "code"
    invite = "invite"


class ModerationMode(str, enum.Enum):
    auto = "auto"
    manual = "manual"


class MemberRole(str, enum.Enum):
    organizer = "organizer"
    attendee = "attendee"


class MemberStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    revoked = "revoked"


class PhotoSource(str, enum.Enum):
    drive = "drive"
    guest = "guest"


class PhotoStatus(str, enum.Enum):
    """Visibility. Only `published` photos may ever appear in search or galleries."""

    processing = "processing"
    published = "published"
    pending_review = "pending_review"
    rejected = "rejected"
    removed = "removed"


class IndexStatus(str, enum.Enum):
    """Pipeline progress: queued → importing → indexing → indexed (or failed)."""

    queued = "queued"
    importing = "importing"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"


class SyncStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class InviteStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class ReportStatus(str, enum.Enum):
    open = "open"
    dismissed = "dismissed"
    photo_removed = "photo_removed"


class RemovalStatus(str, enum.Enum):
    unverified = "unverified"  # email not confirmed yet
    submitted = "submitted"  # awaiting organizer review
    resolved = "resolved"  # photos removed
    declined = "declined"


class FeedbackVerdict(str, enum.Enum):
    me = "me"
    not_me = "not_me"
    missing = "missing"  # "photos of me are missing" (no photo attached)


class ThemePreference(str, enum.Enum):
    system = "system"  # follow the OS (prefers-color-scheme)
    light = "light"
    dark = "dark"
