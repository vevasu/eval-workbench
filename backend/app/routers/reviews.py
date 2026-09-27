"""Human review: a queue of results the automatic checks could not decide, and a person's decision on any result.

A decision replaces verdict and category, so pass rates, comparisons and production numbers use it everywhere. The
automatic verdict and category are kept in review.autoVerdict and review.autoCategory, and undo puts them back.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlmodel import Session, select

from ..auth import current_project
from ..db import get_session
from ..models import Project, Result, Run, now_ms
from ..schemas import ResultOut, ReviewIn
from ..scoring import CATEGORIES
from ..services import get_run_or_404

router = APIRouter(tags=["reviews"])
SPOT_EVERY = 20  # spot checks: 1 in 20 production requests that passed their checks
PREVIEW = 240


def is_spot_check(case_id: str) -> bool:
    """Production requests picked for a spot check, by the number in their id. Same as isSpotCheck() in the frontend."""
    tail = case_id.rsplit("-", 1)[-1]
    return case_id.startswith("LIVE-") and tail.isdigit() and int(tail) % SPOT_EVERY == 0


def _clip(text: str) -> str:
    return text if len(text) <= PREVIEW else text[:PREVIEW] + "…"


def _item(r, suite_id: str, target: str) -> dict:
    return {"runId": r.run_id, "suiteId": suite_id, "caseId": r.case_id, "source": "live" if target == "production" else "runs",
            "timestamp": r.timestamp, "verdict": r.verdict, "category": r.category, "reason": r.reason,
            "input": _clip(r.input), "actual": _clip(r.actual), "version": r.version, "model": r.model, "review": r.review}


@router.get("/reviews")
def queue(kind: str = Query("pending", pattern="^(pending|spot|done)$"), suite: Optional[str] = None,
          source: Optional[str] = Query(None, pattern="^(runs|live)$"), reason: Optional[str] = None,
          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
          project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """pending: results waiting for review, newest first. spot: passing production requests picked for a spot check.
    done: results a person reviewed, most recent decision first. Counts are for all three with the same filters."""
    query = (select(Result, Run.suite_id, Run.target)
             .join(Run, and_(Run.project_id == Result.project_id, Run.id == Result.run_id))
             .where(Result.project_id == project.id)
             .where(or_(Result.reviewed_at.is_not(None), Result.verdict == "Review",
                        and_(Run.target == "production", Result.verdict == "Pass", Result.case_id.like("LIVE-%")))))
    if suite:
        query = query.where(Run.suite_id == suite)
    if source:
        query = query.where(Run.target == "production" if source == "live" else Run.target != "production")
    rows = session.exec(query).all()
    buckets: dict = {"pending": [], "spot": [], "done": []}
    for r, suite_id, target in rows:
        if r.reviewed_at is not None:
            buckets["done"].append((r, suite_id, target))
        elif r.verdict == "Review" and (not reason or r.category == reason):
            buckets["pending"].append((r, suite_id, target))
        elif target == "production" and r.verdict == "Pass" and is_spot_check(r.case_id):
            buckets["spot"].append((r, suite_id, target))
    for k in ("pending", "spot"):
        buckets[k].sort(key=lambda x: (x[0].timestamp, x[0].id), reverse=True)
    buckets["done"].sort(key=lambda x: (x[0].reviewed_at, x[0].id), reverse=True)
    chosen = buckets[kind]
    return {"items": [_item(*x) for x in chosen[offset:offset + limit]], "total": len(chosen),
            "counts": {k: len(v) for k, v in buckets.items()}}


def _result_or_404(session: Session, project_id: str, run_id: str, case_id: str) -> Result:
    run = get_run_or_404(session, project_id, run_id)
    row = session.exec(select(Result).where(Result.project_id == project_id, Result.run_id == run.id,
                                            Result.case_id == case_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return row


@router.post("/runs/{run_id}/results/{case_id}/review", response_model=ResultOut)
def review(run_id: str, case_id: str, body: ReviewIn, project: Project = Depends(current_project),
           session: Session = Depends(get_session)):
    """Record a person's decision. Reviewing again replaces the earlier decision; the automatic verdict is kept."""
    row = _result_or_404(session, project.id, run_id, case_id)
    if body.verdict == "Fail" and body.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Choose why it failed: " + ", ".join(CATEGORIES) + ".")
    auto = row.review or {"autoVerdict": row.verdict, "autoCategory": row.category}
    at = now_ms()
    row.review = {"verdict": body.verdict, "category": body.category if body.verdict == "Fail" else None,
                  "note": body.note.strip(), "reviewer": body.reviewer.strip(), "reviewedAt": at,
                  "autoVerdict": auto["autoVerdict"], "autoCategory": auto["autoCategory"]}
    row.verdict, row.category, row.reviewed_at = body.verdict, row.review["category"], at
    session.add(row)
    session.commit()
    return ResultOut.model_validate(row)


@router.delete("/runs/{run_id}/results/{case_id}/review", response_model=ResultOut)
def undo_review(run_id: str, case_id: str, project: Project = Depends(current_project),
                session: Session = Depends(get_session)):
    """Remove a person's decision and put the automatic verdict back."""
    row = _result_or_404(session, project.id, run_id, case_id)
    if row.review:
        row.verdict, row.category = row.review["autoVerdict"], row.review["autoCategory"]
        row.review, row.reviewed_at = None, None
        session.add(row)
        session.commit()
    return ResultOut.model_validate(row)
