"""Admin CLI.

    python -m app.cli create-superadmin --email admin@example.com
    python -m app.cli init-storage
"""

import argparse
import getpass
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password, utcnow
from app.core.storage import configure_cors, ensure_bucket
from app.models import User, UserRole


def create_superadmin(email: str, password: str | None) -> None:
    try:
        # Same rules as signup, so the account can actually log in.
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        sys.exit(f"Invalid email: {e}")
    password = password or getpass.getpass("Password (min 10 chars): ")
    if len(password) < 10:
        sys.exit("Password must be at least 10 characters")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
        else:
            user.password_hash = hash_password(password)
        user.role = UserRole.super_admin
        user.email_verified_at = user.email_verified_at or utcnow()
        db.commit()
    print(f"Super admin ready: {email}")


def reindex_faces(all_photos: bool = False) -> int:
    """Queue re-indexing after a FACE_ENGINE change. By default only photos with faces from
    another model; `all_photos` also re-scans photos where the old model found no faces.
    Events whose face data was deleted by retention are skipped. Returns photos queued."""
    from app.models import Event, Face, Photo, PhotoStatus
    from app.services.faces import current_model_id
    from app.workers.tasks import index_photo

    model = current_model_id()
    with SessionLocal() as db:
        q = (
            select(Photo.id)
            .join(Event, Event.id == Photo.event_id)
            .where(
                Photo.original_key.is_not(None),
                Photo.status.not_in([PhotoStatus.rejected, PhotoStatus.removed]),
                Event.retention_completed_at.is_(None),
            )
        )
        if not all_photos:
            q = q.where(select(Face.id).where(Face.photo_id == Photo.id, Face.model != model).exists())
        ids = list(db.scalars(q))
    for photo_id in ids:
        index_photo.delay(str(photo_id))
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-superadmin", help="Create or promote a super admin")
    p.add_argument("--email", required=True)
    p.add_argument("--password", help="Omit to be prompted (recommended)")
    sub.add_parser("init-storage", help="Create the object storage bucket if missing")
    r = sub.add_parser("reindex-faces", help="Re-embed photos with the current FACE_ENGINE")
    r.add_argument("--all", action="store_true", help="Also re-scan photos with no faces from the old model")
    args = parser.parse_args()
    if args.command == "create-superadmin":
        create_superadmin(args.email, args.password)
    elif args.command == "reindex-faces":
        print(f"Queued {reindex_faces(all_photos=args.all)} photo(s) for re-indexing")
    elif args.command == "init-storage":
        ensure_bucket()
        try:
            configure_cors([get_settings().frontend_url])
            print(f"Storage bucket ready (CORS: {get_settings().frontend_url})")
        except Exception as e:  # e.g. production keys without bucket-admin rights
            print(f"Storage bucket ready; could not set CORS ({e}). Configure it in your provider's console.")


if __name__ == "__main__":
    main()
