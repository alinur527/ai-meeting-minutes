"""Local operator commands. Passwords are read interactively or from a named environment variable."""

import argparse
import getpass
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update

from .auth import password_hasher
from .config import settings
from .db import SessionLocal
from .models import Meeting, User
from .models.base import utc_now


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument(
        "--password-env", help="Name of an environment variable, never the password"
    )
    claim = sub.add_parser("assign-legacy")
    claim.add_argument("--email", required=True)
    claim.add_argument("--meeting-id", required=True, type=UUID)
    clean = sub.add_parser("cleanup-storage")
    clean.add_argument("--apply", action="store_true", help="Default is a dry run")
    clean.add_argument("--older-than-hours", type=int, default=24)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command == "create-user":
            email = args.email.strip().casefold()
            if (
                "@" not in email
                or len(email) > 254
                or not 1 <= len(args.name.strip()) <= 255
                or db.scalar(select(User.id).where(User.email == email))
            ):
                raise SystemExit("Invalid or existing email")
            password = (
                os.environ.get(args.password_env, "")
                if args.password_env
                else getpass.getpass("Password (12+ characters): ")
            )
            if not 12 <= len(password) <= 1024:
                raise SystemExit("Password must contain 12 to 1024 characters")
            db.add(
                User(
                    email=email,
                    name=args.name.strip(),
                    password_hash=password_hasher.hash(password),
                )
            )
            db.commit()
            print("User created")
        elif args.command == "assign-legacy":
            user = db.scalar(
                select(User).where(User.email == args.email.strip().casefold())
            )
            if user is None:
                raise SystemExit("User not found")
            result = db.execute(
                update(Meeting)
                .where(Meeting.id == args.meeting_id, Meeting.owner_id.is_(None))
                .values(owner_id=user.id)
            )
            db.commit()
            print(f"Assigned {result.rowcount} legacy meeting(s)")
        else:
            if args.older_than_hours < 24:
                raise SystemExit("Cleanup grace period must be at least 24 hours")
            root = Path(settings.storage_dir).resolve()
            referenced = {
                Path(p).resolve() for p in db.scalars(select(Meeting.audio_path)) if p
            }
            cutoff = (utc_now() - timedelta(hours=args.older_than_hours)).timestamp()
            candidates = [
                p
                for p in root.iterdir()
                if p.is_file()
                and not p.is_symlink()
                and p.resolve().parent == root
                and p.resolve() not in referenced
                and p.stat().st_mtime < cutoff
            ]
            for path in candidates:
                if args.apply:
                    path.unlink()
            print(
                f"{'Removed' if args.apply else 'Would remove'} {len(candidates)} unreferenced old files"
            )


if __name__ == "__main__":
    main()
