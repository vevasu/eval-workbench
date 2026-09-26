from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from .. import beta
from ..auth import require_admin
from ..db import get_session
from ..models import AccessRequest
from ..ratelimit import client_ip, hit
from ..schemas import CamelModel
from ..settings import limits

router = APIRouter(tags=["access"])


class AccessIn(CamelModel):
    email: str
    name: str = ""
    use_case: str = ""
    website: str = ""  # honeypot: real people leave this empty, form-filling bots don't


@router.post("/access-requests", status_code=201)
def request_access(body: AccessIn, request: Request, session: Session = Depends(get_session)):
    """Public. Anyone can ask for beta access; nothing is granted until the operator approves."""
    hit(f"access:{client_ip(request)}", limits()["access_requests_per_hour"], 3600)
    if body.website:
        return {"status": "received"}
    beta.create_request(session, body.email, body.name, body.use_case)
    return {"status": "received"}


admin = APIRouter(prefix="/admin/access-requests", tags=["admin"], dependencies=[Depends(require_admin)])


@admin.get("")
def list_requests(status: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(AccessRequest).order_by(AccessRequest.created_at)
    if status:
        query = query.where(AccessRequest.status == status)
    return [beta.request_row(r) for r in session.exec(query).all()]


@admin.post("/{request_id}/approve")
def approve_request(request_id: int, session: Session = Depends(get_session)):
    return beta.approve(session, request_id)


@admin.delete("/{request_id}", status_code=204)
def delete_request(request_id: int, session: Session = Depends(get_session)):
    beta.delete_request(session, request_id)


@admin.post("/{request_id}/reject")
def reject_request(request_id: int, session: Session = Depends(get_session)):
    return beta.request_row(beta.reject(session, request_id))
