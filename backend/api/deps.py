"""Shared FastAPI dependencies — current user resolution and ownership checks."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import User, Project
from backend.api.security import decode_access_token, COOKIE_NAME


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "not authenticated")
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(401, "invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "user no longer exists")
    return user


def owned_project_or_404(db: Session, project_id: int, user: User) -> Project:
    """Fetch a project only if it belongs to the user. 404 (not 403) so we don't
    leak the existence of other users' projects."""
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(404, "project not found")
    return project
