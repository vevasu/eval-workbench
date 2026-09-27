from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..auth import current_project
from ..db import get_session
from ..models import Project, TestCase
from ..schemas import CaseIn, CaseOut, CasePatch
from ..serialize import cases_for
from ..services import add_case, get_suite_or_404, validate_checks

router = APIRouter(prefix="/suites/{suite_id}/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
def list_cases(suite_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    get_suite_or_404(session, project.id, suite_id)
    return cases_for(session, project.id, suite_id)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(suite_id: str, body: CaseIn, project: Project = Depends(current_project),
                session: Session = Depends(get_session)):
    suite = get_suite_or_404(session, project.id, suite_id)
    case = add_case(session, suite, body.model_dump())
    session.commit()
    return case


@router.get("/{case_id}", response_model=CaseOut)
def get_case(suite_id: str, case_id: str, project: Project = Depends(current_project),
             session: Session = Depends(get_session)):
    case = session.get(TestCase, (project.id, suite_id, case_id))
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(suite_id: str, case_id: str, body: CasePatch, project: Project = Depends(current_project),
                session: Session = Depends(get_session)):
    case = session.get(TestCase, (project.id, suite_id, case_id))
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    changes = body.model_dump(exclude_unset=True)
    if "checks" in changes:
        validate_checks(changes["checks"] or [])
    for field, value in changes.items():
        setattr(case, field, value)
    session.add(case)
    session.commit()
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(suite_id: str, case_id: str, project: Project = Depends(current_project),
                session: Session = Depends(get_session)):
    """Delete a test case. Past results keep their own copy of its input and expected behaviour."""
    case = session.get(TestCase, (project.id, suite_id, case_id))
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    session.delete(case)
    session.commit()
