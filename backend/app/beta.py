"""Private beta: access requests and approving them into a project plus an API key."""
import re
import secrets
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from .auth import hash_key, new_key
from .models import AccessRequest, ApiKey, Project, now_ms

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def create_request(session: Session, email: str, name: str = "", use_case: str = "") -> AccessRequest:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    existing = session.exec(select(AccessRequest).where(AccessRequest.email == email, AccessRequest.status == "pending")).first()
    if existing:
        return existing
    req = AccessRequest(email=email, name=name.strip()[:100], use_case=use_case.strip()[:1000])
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def _project_id(session: Session, req: AccessRequest) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (req.name or req.email.split("@")[0]).lower()).strip("-")[:30] or "project"
    pid, n = base, 2
    while session.get(Project, pid):
        pid, n = f"{base}-{n}", n + 1
    return pid


def approve(session: Session, request_id: int, project_name: Optional[str] = None) -> dict:
    """Create a project and one API key for the requester. The full key is returned once; only its hash is stored."""
    req = session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    if req.status == "approved":
        raise HTTPException(status_code=409, detail="Already approved. Create another key for that project if needed.")
    project = Project(id=_project_id(session, req), name=project_name or req.name or req.email)
    key = new_key()
    session.add(project)
    session.flush()  # Postgres enforces foreign keys: the project row must exist before its key
    session.add(ApiKey(id=secrets.token_hex(6), project_id=project.id, name="beta", prefix=key[:12], key_hash=hash_key(key)))
    req.status, req.project_id, req.decided_at = "approved", project.id, now_ms()
    session.add(req)
    session.commit()
    return {"requestId": req.id, "email": req.email, "projectId": project.id, "key": key}


def reject(session: Session, request_id: int) -> AccessRequest:
    req = session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    req.status, req.decided_at = "rejected", now_ms()
    session.add(req)
    session.commit()
    return req


def request_row(r: AccessRequest) -> dict:
    return {"id": r.id, "email": r.email, "name": r.name, "useCase": r.use_case, "status": r.status,
            "projectId": r.project_id, "createdAt": r.created_at, "decidedAt": r.decided_at}
