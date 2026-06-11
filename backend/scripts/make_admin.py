"""Promote a user to the admin role (there is no self-service path to admin).

Usage:
    python -m backend.scripts.make_admin user@example.com
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import select
from backend.db.base import SessionLocal
from backend.db.models.app import User


def make_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"no user with email {email!r}", file=sys.stderr)
            sys.exit(1)
        user.role = "admin"
        db.commit()
        print(f"{email} is now an admin")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m backend.scripts.make_admin <email>", file=sys.stderr)
        sys.exit(2)
    make_admin(sys.argv[1])
