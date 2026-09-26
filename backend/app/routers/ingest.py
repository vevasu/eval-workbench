from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth import current_project
from ..limits import check_result_quota, check_spans, check_text
from ..ratelimit import hit
from ..settings import limits
from ..db import get_session
from ..models import Project, Result, Run, Span, Suite, now_ms
from ..schemas import CamelModel, ResultOut, SpanIn
from ..scoring import evaluate
from ..serialize import results_for
from ..services import create_suite, next_run_id, validate_checks

router = APIRouter(tags=["ingest"])


class TraceIn(CamelModel):
    suite_id: str
    suite_name: Optional[str] = None
    input: str
    actual: str = ""
    latency_ms: int = 0
    timestamp: Optional[int] = None
    spans: list[SpanIn] = []
    error: Optional[str] = None
    version: str = ""
    model: str = ""
    checks: list[dict] = []


@router.post("/ingest", status_code=201)
def ingest_trace(body: TraceIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Record one real request from a running application as an execution, scored by the checks it sends."""
    hit(f"ingest:{project.id}", limits()["ingest_per_minute"], 60)
    check_text(input=body.input, actual=body.actual)
    check_spans(body.spans)
    validate_checks(body.checks)
    check_result_quota(session, project.id)
    suite = session.get(Suite, (project.id, body.suite_id))
    if suite is None:
        suite = create_suite(session, project.id, {"id": body.suite_id, "name": body.suite_name or body.suite_id})
        session.flush()

    # One long-lived "production" run per version and model, so a new deploy starts a new run.
    run = session.exec(select(Run).where(
        Run.project_id == project.id, Run.suite_id == suite.id, Run.target == "production",
        Run.version == body.version, Run.model == body.model)).first()
    if run is None:
        run = Run(project_id=project.id, id=next_run_id(session, suite), suite_id=suite.id, version=body.version,
                  model=body.model, target="production", note="Live traffic", started_at=body.timestamp or now_ms(),
                  sla_ms=suite.sla_ms)
        session.add(run)
        session.flush()

    ev = evaluate(body.checks, body.actual, body.latency_ms, run.sla_ms, body.error)
    row = Result(project_id=project.id, run_id=run.id, case_id="pending", input=body.input, expected="", actual=body.actual,
                 verdict=ev["verdict"], category=ev["category"], reason=ev["reason"], checks=ev["checks"],
                 latency_ms=body.latency_ms, timestamp=body.timestamp or now_ms(), model=body.model, version=body.version)
    session.add(row)
    session.flush()
    row.case_id = f"LIVE-{row.id:05d}"
    session.add(row)
    for s in body.spans:
        session.add(Span(result_id=row.id, name=s.name, kind=s.kind, start=s.start, dur=s.dur, depth=s.depth, attrs=s.attrs))
    run.finished_at = row.timestamp + row.latency_ms
    session.add(run)
    session.commit()
    stored = next(r for r in results_for(session, project.id, run.id) if r.case_id == row.case_id)
    return {"runId": run.id, "result": stored}
