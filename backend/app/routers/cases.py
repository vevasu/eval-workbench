from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import TestCase
from ..schemas import CaseOut

router = APIRouter(tags=["cases"])


@router.get("/suites/{suite_id}/cases", response_model=list[CaseOut])
def list_cases(suite_id: str, session: Session = Depends(get_session)):
    return session.exec(select(TestCase).where(TestCase.suite_id == suite_id)).all()


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
