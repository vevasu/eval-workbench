"""Beta allowances and size caps. Checked on every write that stores data."""
import json

from fastapi import HTTPException
from sqlmodel import Session, func, select

from .models import Result, Suite
from .settings import limits


def result_count(session: Session, project_id: str) -> int:
    return session.exec(select(func.count()).select_from(Result).where(Result.project_id == project_id)).one()


def suite_count(session: Session, project_id: str) -> int:
    return session.exec(select(func.count()).select_from(Suite).where(Suite.project_id == project_id)).one()


def check_result_quota(session: Session, project_id: str, adding: int = 1) -> None:
    cap = limits()["max_results"]
    if result_count(session, project_id) + adding > cap:
        raise HTTPException(status_code=429, detail=f"This project has reached its beta allowance of {cap} stored executions. "
                                                    "Ask the Workbench operator for more.")


def check_suite_quota(session: Session, project_id: str) -> None:
    cap = limits()["max_suites"]
    if suite_count(session, project_id) >= cap:
        raise HTTPException(status_code=429, detail=f"This project has reached its limit of {cap} suites.")


def check_text(**fields: str) -> None:
    cap = limits()["max_text_chars"]
    for name, value in fields.items():
        if value and len(value) > cap:
            raise HTTPException(status_code=413, detail=f"'{name}' is longer than {cap} characters.")


def check_spans(spans: list) -> None:
    cap = limits()["max_spans"]
    if len(spans) > cap:
        raise HTTPException(status_code=413, detail=f"An execution can have at most {cap} spans.")


def check_trace_context(user_id, session_id, tags: list, metadata: dict) -> None:
    """User and session ids, tags and metadata are for grouping and filtering, so they stay small."""
    for name, value in (("userId", user_id), ("sessionId", session_id)):
        if value and len(value) > 200:
            raise HTTPException(status_code=413, detail=f"'{name}' is longer than 200 characters.")
    if len(tags) > 20 or any(len(t) > 60 for t in tags):
        raise HTTPException(status_code=413, detail="Send at most 20 tags of up to 60 characters each.")
    if metadata and len(json.dumps(metadata, default=str)) > 4000:
        raise HTTPException(status_code=413, detail="'metadata' is larger than 4000 characters as JSON.")
