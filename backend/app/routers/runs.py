from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Result, Run, Span
from ..schemas import ResultOut, RunOut, SpanOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def list_runs(suite_id: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(Run)
    if suite_id:
        query = query.where(Run.suite_id == suite_id)
    return session.exec(query.order_by(Run.started_at)).all()


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    results = session.exec(select(Result).where(Result.run_id == run_id)).all()
    out = RunOut.model_validate(run)
    out.results = [ResultOut.model_validate(r) for r in results]
    return out


@router.get("/{run_id}/results", response_model=list[ResultOut])
def list_results(run_id: str, session: Session = Depends(get_session)):
    if session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return session.exec(select(Result).where(Result.run_id == run_id)).all()


@router.get("/{run_id}/results/{case_id}", response_model=ResultOut)
def get_result(run_id: str, case_id: str, session: Session = Depends(get_session)):
    result = session.exec(
        select(Result).where(Result.run_id == run_id, Result.case_id == case_id)
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    spans = session.exec(select(Span).where(Span.result_id == result.id).order_by(Span.start)).all()
    out = ResultOut.model_validate(result)
    out.spans = [SpanOut.model_validate(s) for s in spans]
    return out
