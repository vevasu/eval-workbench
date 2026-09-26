import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from .db import get_session
from .models import ApiKey, Project


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return "ewb_" + secrets.token_urlsafe(32)


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing API key. Send 'Authorization: Bearer <key>'.")
    return authorization[7:].strip()


def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    admin_key = os.environ.get("EVAL_WORKBENCH_ADMIN_KEY", "")
    if not admin_key:
        raise HTTPException(status_code=503, detail="Admin access is off. Set EVAL_WORKBENCH_ADMIN_KEY in backend/.env.")
    if not hmac.compare_digest(_bearer(authorization), admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key.")


def current_project(
    authorization: Optional[str] = Header(default=None), session: Session = Depends(get_session)
) -> Project:
    key = _bearer(authorization)
    record = session.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(key))).first()
    if record is None or record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    project = session.get(Project, record.project_id)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return project
