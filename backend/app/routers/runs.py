from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import current_project
from ..db import get_session
from ..models import Project, Result, Run, Span, TestCase, now_ms
from ..schemas import CaseOut, ResultIn, ResultOut, ResultsIn, RunIn, RunOut
from ..scoring import compare_runs, evaluate, summarize
from ..serialize import cases_for, results_for, run_out
from ..services import get_run_or_404, get_suite_or_404, next_run_id

router = APIRouter(tags=["runs"])


def _dump(results: list[ResultOut]) -> list[dict]:
    return [r.model_dump(by_alias=True) for r in results]


@router.get("/runs", response_model=list[RunOut])
def list_runs(suite_id: Optional[str] = None, project: Project = Depends(current_project),
              session: Session = Depends(get_session)):
    query = select(Run).where(Run.project_id == project.id)
    if suite_id:
        query = query.where(Run.suite_id == suite_id)
    return [run_out(session, r) for r in session.exec(query.order_by(Run.started_at)).all()]


@router.post("/runs", status_code=201)
def create_run(body: RunIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    suite = get_suite_or_404(session, project.id, body.suite_id)
    run = Run(project_id=project.id, id=next_run_id(session, suite), suite_id=suite.id, version=body.version,
              model=body.model, target=body.target, note=body.note, started_at=now_ms(), sla_ms=suite.sla_ms)
    session.add(run)
    session.commit()
    return {"run": run_out(session, run), "cases": [CaseOut.model_validate(c) for c in cases_for(session, project.id, suite.id)]}


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    return run_out(session, get_run_or_404(session, project.id, run_id), with_results=True)


@router.get("/runs/{run_id}/results", response_model=list[ResultOut])
def list_results(run_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    get_run_or_404(session, project.id, run_id)
    return results_for(session, project.id, run_id)


@router.get("/runs/{run_id}/results/{case_id}", response_model=ResultOut)
def get_result(run_id: str, case_id: str, project: Project = Depends(current_project),
               session: Session = Depends(get_session)):
    get_run_or_404(session, project.id, run_id)
    for r in results_for(session, project.id, run_id, with_spans=True):
        if r.case_id == case_id:
            return r
    raise HTTPException(status_code=404, detail="Execution not found")


def _store_result(session: Session, run: Run, case: TestCase, body: ResultIn) -> None:
    old = session.exec(select(Result).where(
        Result.project_id == run.project_id, Result.run_id == run.id, Result.case_id == case.id)).all()
    for r in old:
        for s in session.exec(select(Span).where(Span.result_id == r.id)).all():
            session.delete(s)
        session.delete(r)
    ev = evaluate(case.checks, body.actual, body.latency_ms, run.sla_ms, body.error)
    row = Result(
        project_id=run.project_id, run_id=run.id, case_id=case.id, input=case.input, expected=case.expected,
        actual=body.actual, verdict=ev["verdict"], category=ev["category"], reason=ev["reason"], checks=ev["checks"],
        latency_ms=body.latency_ms, timestamp=body.timestamp or now_ms(), model=run.model, version=run.version)
    session.add(row)
    session.flush()
    for s in body.spans:
        session.add(Span(result_id=row.id, name=s.name, kind=s.kind, start=s.start, dur=s.dur, depth=s.depth, attrs=s.attrs))


@router.post("/runs/{run_id}/results")
def add_results(run_id: str, body: ResultsIn, project: Project = Depends(current_project),
                session: Session = Depends(get_session)):
    run = get_run_or_404(session, project.id, run_id)
    if run.finished_at is not None:
        raise HTTPException(status_code=409, detail="This run is already complete.")
    cases = {c.id: c for c in cases_for(session, project.id, run.suite_id)}
    unknown = [r.case_id for r in body.results if r.case_id not in cases]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown case ids: {', '.join(unknown)}")
    for r in body.results:
        _store_result(session, run, cases[r.case_id], r)
    session.commit()
    stored = {r.case_id: r for r in results_for(session, project.id, run.id)}
    return {"results": [stored[r.case_id] for r in body.results]}


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    run = get_run_or_404(session, project.id, run_id)
    if run.finished_at is None:
        run.finished_at = now_ms()
        session.add(run)
        session.commit()
    return {"run": run_out(session, run), "summary": summarize(_dump(results_for(session, project.id, run.id)))}


@router.get("/runs/{run_id}/summary")
def run_summary(run_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    run = get_run_or_404(session, project.id, run_id)
    return summarize(_dump(results_for(session, project.id, run.id)))


@router.get("/compare")
def compare(a: str, b: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    run_a, run_b = get_run_or_404(session, project.id, a), get_run_or_404(session, project.id, b)
    ra, rb = _dump(results_for(session, project.id, run_a.id)), _dump(results_for(session, project.id, run_b.id))
    return {"a": {"run": run_out(session, run_a), "summary": summarize(ra)},
            "b": {"run": run_out(session, run_b), "summary": summarize(rb)},
            "diff": compare_runs(ra, rb)}
