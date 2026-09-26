import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import beta
from ..auth import hash_key, new_key, require_admin
from ..db import get_session
from ..models import ApiKey, Project, now_ms
from ..schemas import KeyIn, ProjectIn

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _key_row(k: ApiKey) -> dict:
    return {"id": k.id, "projectId": k.project_id, "name": k.name, "prefix": k.prefix,
            "createdAt": k.created_at, "revokedAt": k.revoked_at}


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, session: Session = Depends(get_session)):
    pid = body.id or re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") or "project"
    if session.get(Project, pid):
        raise HTTPException(status_code=409, detail=f"Project '{pid}' already exists.")
    project = Project(id=pid, name=body.name)
    session.add(project)
    session.commit()
    return {"id": project.id, "name": project.name, "createdAt": project.created_at}


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)):
    return [{"id": p.id, "name": p.name, "createdAt": p.created_at} for p in session.exec(select(Project)).all()]


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, session: Session = Depends(get_session)):
    """Permanently delete a project and all its data, keys and access request."""
    return beta.delete_project(session, project_id)


@router.post("/projects/{project_id}/keys", status_code=201)
def create_key(project_id: str, body: KeyIn, session: Session = Depends(get_session)):
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    key = new_key()
    record = ApiKey(id=secrets.token_hex(6), project_id=project_id, name=body.name, prefix=key[:12], key_hash=hash_key(key))
    session.add(record)
    session.commit()
    # The full key is returned once. Only its hash is stored.
    return {**_key_row(record), "key": key}


@router.get("/projects/{project_id}/keys")
def list_keys(project_id: str, session: Session = Depends(get_session)):
    keys = session.exec(select(ApiKey).where(ApiKey.project_id == project_id).order_by(ApiKey.created_at)).all()
    return [_key_row(k) for k in keys]


@router.delete("/keys/{key_id}")
def revoke_key(key_id: str, session: Session = Depends(get_session)):
    record = session.get(ApiKey, key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Key not found")
    if record.revoked_at is None:
        record.revoked_at = now_ms()
        session.add(record)
        session.commit()
    return _key_row(record)
