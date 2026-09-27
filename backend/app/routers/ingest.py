import random
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth import current_project
from ..limits import check_result_quota, check_spans, check_text, check_trace_context
from ..ratelimit import hit
from ..settings import limits
from ..db import engine, get_session
from ..models import Project, Result, Run, Span, Suite, now_ms
from ..schemas import CamelModel, ResultOut, SpanIn
from ..judge import judge_later, needs_judge
from ..scoring import evaluate, span_totals
from ..serialize import results_for
from ..services import create_suite, matching_cases, next_run_id, validate_checks

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
    user_id: Optional[str] = None      # your end user, to see who is affected by a failure
    session_id: Optional[str] = None   # groups the requests of one conversation or task
    tags: list[str] = []               # for filtering, such as a feature name or customer tier
    metadata: dict = {}                # anything else worth seeing on the trace


@router.post("/ingest", status_code=201)
def ingest_trace(body: TraceIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Record one real request from a running application as an execution, scored by the checks it sends."""
    hit(f"ingest:{project.id}", limits()["ingest_per_minute"], 60)
    check_text(input=body.input, actual=body.actual)
    check_spans(body.spans)
    check_trace_context(body.user_id, body.session_id, body.tags, body.metadata)
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

    # The app's own checks, then the suite's live checks set in the web app. An AI judge runs on its sample of requests.
    # A prompt that is the same as a test case's input is also checked by that test case, so a suite you import applies
    # to the next live request straight away.
    matched = matching_cases(session, project.id, body.input)
    case_checks = [{**c, "fromCase": f"{m.suite_id}/{m.id}"} for m in matched for c in (m.checks or [])]
    checks = [c for c in body.checks + case_checks + (suite.live_checks or [])
              if c.get("type") != "llm_judge" or random.random() * 100 < c.get("sample", 100)]
    ev = evaluate(checks, body.actual, body.latency_ms, run.sla_ms, body.error, live=True)
    totals = span_totals([s.model_dump() for s in body.spans])
    expected = next((m.expected for m in matched if m.expected), "")
    row = Result(project_id=project.id, run_id=run.id, case_id="pending", input=body.input, expected=expected, actual=body.actual,
                 verdict=ev["verdict"], category=ev["category"], reason=ev["reason"], checks=ev["checks"],
                 latency_ms=body.latency_ms, timestamp=body.timestamp or now_ms(), model=body.model, version=body.version,
                 user_id=body.user_id or None, session_id=body.session_id or None, tags=body.tags or None,
                 meta=body.metadata or None, tokens_in=totals["tokensIn"], tokens_out=totals["tokensOut"],
                 cost_usd=totals["costUsd"])
    session.add(row)
    session.flush()
    row.case_id = f"LIVE-{row.id:05d}"
    session.add(row)
    for s in body.spans:
        session.add(Span(result_id=row.id, name=s.name, kind=s.kind, start=s.start, dur=s.dur, depth=s.depth, attrs=s.attrs))
    run.finished_at = row.timestamp + row.latency_ms
    session.add(run)
    session.commit()
    if needs_judge(ev):
        judge_later(engine, project.id, [row.id])
    stored = next(r for r in results_for(session, project.id, run.id) if r.case_id == row.case_id)
    return {"runId": run.id, "result": stored}
