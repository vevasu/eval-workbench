from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Suite, TestCase
from ..schemas import CaseOut, SuiteOut

router = APIRouter(prefix="/suites", tags=["suites"])


@router.get("", response_model=list[SuiteOut])
def list_suites(project_id: str = "demo", session: Session = Depends(get_session)):
    return session.exec(select(Suite).where(Suite.project_id == project_id)).all()


@router.get("/{suite_id}", response_model=SuiteOut)
def get_suite(suite_id: str, session: Session = Depends(get_session)):
    suite = session.get(Suite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    cases = session.exec(select(TestCase).where(TestCase.suite_id == suite_id)).all()
    out = SuiteOut.model_validate(suite)
    out.cases = [CaseOut.model_validate(c) for c in cases]
    return out
