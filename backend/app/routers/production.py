"""Read API for production traffic: the executions recorded by POST /ingest (runs with target "production").

These are kept out of GET /state because live traffic grows without bound. The web app pages through them here.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, cast, func, or_
from sqlmodel import Session, select

from ..auth import current_project
from ..db import get_session
from ..live import DAY, default_bucket, live_stats
from ..models import Project, Result, Run, Span, Suite, now_ms
from ..schemas import ResultOut, SpanOut
from ..serialize import run_out
from ..services import get_run_or_404

router = APIRouter(prefix="/production", tags=["production"])

ROW_COLUMNS = (Result.id, Result.run_id, Run.suite_id, Result.case_id, Result.timestamp, Result.verdict, Result.category,
               Result.latency_ms, Result.version, Result.model, Result.user_id, Result.session_id, Result.tokens_in,
               Result.tokens_out, Result.cost_usd)
PREVIEW = 240


def _live(project_id: str, *columns):
    return (select(*columns)
            .join(Run, and_(Run.project_id == Result.project_id, Run.id == Result.run_id))
            .where(Result.project_id == project_id, Run.target == "production"))


def _row(r) -> dict:
    return {"runId": r.run_id, "suiteId": r.suite_id, "caseId": r.case_id, "timestamp": r.timestamp, "verdict": r.verdict,
            "category": r.category, "latencyMs": r.latency_ms, "version": r.version, "model": r.model, "userId": r.user_id,
            "sessionId": r.session_id, "tokensIn": r.tokens_in, "tokensOut": r.tokens_out, "costUsd": r.cost_usd}


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _clip(text: str) -> str:
    return text if len(text) <= PREVIEW else text[:PREVIEW] + "…"


@router.get("/stats")
def stats(suite: Optional[str] = None, version: Optional[str] = None, frm: Optional[int] = Query(None, alias="from"),
          to: Optional[int] = None, bucket: Optional[int] = None, project: Project = Depends(current_project),
          session: Session = Depends(get_session)):
    """Volume, failure rate, latency, tokens and cost for a window, by time bucket and by deployed version."""
    to = to if to is not None else now_ms()
    frm = frm if frm is not None else to - 7 * DAY
    length = to - frm
    if length <= 0 or length > 400 * DAY:
        raise HTTPException(status_code=422, detail="'from' must be before 'to', and the window at most 400 days.")
    bucket = bucket or default_bucket(length)
    if bucket < 60000 or length / bucket > 400:
        raise HTTPException(status_code=422, detail="Use a bucket of at least a minute and at most 400 buckets per window.")
    query = _live(project.id, *ROW_COLUMNS).where(Result.timestamp > frm - length, Result.timestamp <= to)
    if suite:
        query = query.where(Run.suite_id == suite)
    if version:
        query = query.where(Run.version == version)
    rows = [_row(r) for r in session.exec(query.order_by(Result.timestamp, Result.id)).all()]
    out = live_stats(rows, frm, to, bucket)

    per_suite = session.exec(_live(project.id, Run.suite_id, func.count(Result.id), func.max(Result.timestamp))
                             .group_by(Run.suite_id)).all()
    names = {s.id: s.name for s in session.exec(select(Suite).where(Suite.project_id == project.id)).all()}
    out["suites"] = [{"suiteId": sid, "name": names.get(sid, sid), "n": n, "last": last} for sid, n, last in per_suite]
    out["latest"] = max([s["last"] for s in out["suites"] if not suite or s["suiteId"] == suite], default=None)
    return out


@router.get("/traces")
def traces(suite: Optional[str] = None, version: Optional[str] = None, verdict: Optional[str] = None,
           category: Optional[str] = None, user: Optional[str] = None, session_id: Optional[str] = Query(None, alias="session"),
           tag: Optional[str] = None, q: Optional[str] = None, frm: Optional[int] = Query(None, alias="from"),
           to: Optional[int] = None, limit: int = Query(50, ge=1, le=200), before: Optional[int] = None,
           project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Production executions, newest first, with filters. Page with `before` set to the previous page's `next`."""
    query = _live(project.id, *ROW_COLUMNS, Result.input, Result.actual, Result.reason, Result.tags)
    for column, value in ((Run.suite_id, suite), (Run.version, version), (Result.verdict, verdict),
                          (Result.category, category), (Result.user_id, user), (Result.session_id, session_id)):
        if value:
            query = query.where(column == value)
    if tag:
        query = query.where(cast(Result.tags, String).like(_like(json.dumps(tag)), escape="\\"))
    if q:
        query = query.where(or_(Result.input.ilike(_like(q), escape="\\"), Result.actual.ilike(_like(q), escape="\\")))
    if frm is not None:
        query = query.where(Result.timestamp > frm)
    if to is not None:
        query = query.where(Result.timestamp <= to)
    if before is not None:
        query = query.where(Result.id < before)
    rows = session.exec(query.order_by(Result.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    out = [{**_row(r), "input": _clip(r.input), "actual": _clip(r.actual), "reason": r.reason, "tags": r.tags} for r in page]
    return {"traces": out, "next": page[-1].id if len(rows) > limit else None}


@router.get("/traces/{run_id}/{case_id}")
def trace(run_id: str, case_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """One production execution with its spans, its run and suite, and the other requests in its session."""
    run = get_run_or_404(session, project.id, run_id)
    row = session.exec(select(Result).where(Result.project_id == project.id, Result.run_id == run.id,
                                            Result.case_id == case_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    result = ResultOut.model_validate(row)
    result.spans = [SpanOut.model_validate(s) for s in
                    session.exec(select(Span).where(Span.result_id == row.id).order_by(Span.id)).all()]
    suite = session.get(Suite, (project.id, run.suite_id))
    in_session = []
    if row.session_id:
        query = _live(project.id, *ROW_COLUMNS).where(Result.session_id == row.session_id)
        in_session = [_row(r) for r in session.exec(query.order_by(Result.timestamp, Result.id).limit(100)).all()]
    return {"run": run_out(session, run),
            "suite": {"id": run.suite_id, "name": suite.name if suite else run.suite_id, "slaMs": suite.sla_ms if suite else run.sla_ms},
            "result": result.model_dump(by_alias=True), "session": in_session}
