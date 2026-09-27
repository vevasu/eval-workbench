"""Load data/sample-data.json into a demo project.

Run with: python -m app.seed
"""
import json
import secrets
from pathlib import Path

from sqlmodel import Session, delete, select

from .auth import hash_key, new_key
from .db import engine, init_db
from .models import ApiKey, Project, Result, Run, Span, Suite, TestCase

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sample-data.json"
DEMO_PROJECT_ID = "demo"
DEMO_PROJECT_NAME = "Demo project"


def _wipe_sample(session: Session, project_id: str, suite_ids: list) -> None:
    """Remove only the sample suites and their runs, so re-seeding never touches other data in the project."""
    run_ids = session.exec(select(Run.id).where(Run.project_id == project_id, Run.suite_id.in_(suite_ids))).all()
    if run_ids:
        result_ids = session.exec(select(Result.id).where(Result.project_id == project_id, Result.run_id.in_(run_ids))).all()
        if result_ids:
            session.exec(delete(Span).where(Span.result_id.in_(result_ids)))
        session.exec(delete(Result).where(Result.project_id == project_id, Result.run_id.in_(run_ids)))
        session.exec(delete(Run).where(Run.project_id == project_id, Run.id.in_(run_ids)))
    session.exec(delete(TestCase).where(TestCase.project_id == project_id, TestCase.suite_id.in_(suite_ids)))
    session.exec(delete(Suite).where(Suite.project_id == project_id, Suite.id.in_(suite_ids)))
    session.commit()


def seed(session: Session, project_id: str = DEMO_PROJECT_ID) -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    if session.get(Project, project_id) is None:
        session.add(Project(id=project_id, name=DEMO_PROJECT_NAME))
        session.commit()
    else:
        _wipe_sample(session, project_id, [suite["id"] for suite in data["suites"]])

    for suite_data in data["suites"]:
        session.add(Suite(
            project_id=project_id, id=suite_data["id"], prefix=suite_data["prefix"], name=suite_data["name"],
            description=suite_data.get("description", ""), pipeline=suite_data["pipeline"], sla_ms=suite_data["slaMs"],
            system_prompt=suite_data.get("systemPrompt", ""), context=suite_data.get("context"),
            created_at=suite_data["createdAt"]))
        for position, case_data in enumerate(suite_data["cases"]):
            session.add(TestCase(
                project_id=project_id, suite_id=suite_data["id"], id=case_data["id"], position=position,
                tag=case_data.get("tag", ""), input=case_data["input"], expected=case_data.get("expected", ""),
                checks=case_data.get("checks", []), recorded=case_data.get("recorded"),
                recorded_latency_ms=case_data.get("recordedLatencyMs"), origin=case_data.get("origin")))

    for run_data in data["runs"]:
        session.add(Run(
            project_id=project_id, id=run_data["id"], suite_id=run_data["suiteId"], version=run_data.get("version", ""),
            model=run_data.get("model", ""), target=run_data.get("target", "simulated"), note=run_data.get("note", ""),
            started_at=run_data["startedAt"], finished_at=run_data.get("finishedAt"), sla_ms=run_data["slaMs"]))
        for result_data in run_data["results"]:
            result = Result(
                project_id=project_id, run_id=run_data["id"], case_id=result_data["caseId"],
                input=result_data.get("input", ""), expected=result_data.get("expected", ""),
                actual=result_data.get("actual", ""), verdict=result_data["verdict"], category=result_data.get("category"),
                reason=result_data.get("reason", ""), checks=result_data.get("checks", []),
                latency_ms=result_data.get("latencyMs", 0), timestamp=result_data["timestamp"],
                model=result_data.get("model", ""), version=result_data.get("version", ""),
                user_id=result_data.get("userId"), session_id=result_data.get("sessionId"), tags=result_data.get("tags"),
                meta=result_data.get("metadata"), tokens_in=result_data.get("tokensIn"),
                tokens_out=result_data.get("tokensOut"), cost_usd=result_data.get("costUsd"),
                review=result_data.get("review"),
                reviewed_at=(result_data.get("review") or {}).get("reviewedAt"))
            session.add(result)
            session.flush()
            for span_data in result_data.get("spans", []):
                session.add(Span(
                    result_id=result.id, name=span_data["name"], kind=span_data.get("kind", "other"),
                    start=span_data.get("start", 0), dur=span_data.get("dur", 0), depth=span_data.get("depth", 0),
                    attrs=span_data.get("attrs", {})))
    session.commit()


def ensure_demo_key(session: Session, project_id: str = DEMO_PROJECT_ID):
    """Create an API key for the demo project if it has no active one. Returns the key, shown once."""
    active = session.exec(select(ApiKey).where(ApiKey.project_id == project_id, ApiKey.revoked_at == None)).first()  # noqa: E711
    if active:
        return None
    key = new_key()
    session.add(ApiKey(id=secrets.token_hex(6), project_id=project_id, name="demo key", prefix=key[:12], key_hash=hash_key(key)))
    session.commit()
    return key


def main() -> None:
    init_db()
    with Session(engine) as session:
        seed(session)
        key = ensure_demo_key(session)
    print(f"Seeded project '{DEMO_PROJECT_ID}' from {DATA_PATH}")
    if key:
        print(f"Demo API key (shown once, save it): {key}")
    else:
        print("The demo project already has an API key. Create another with POST /admin/projects/demo/keys.")


if __name__ == "__main__":
    main()
