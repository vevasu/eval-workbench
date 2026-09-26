"""Load data/sample-data.json into a demo project.

Run with: python -m app.seed
"""
import json
from pathlib import Path

from sqlmodel import Session, select

from .db import engine, init_db
from .models import Project, Result, Run, Span, Suite, TestCase

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sample-data.json"
DEMO_PROJECT_ID = "demo"
DEMO_PROJECT_NAME = "Demo project"


def _wipe_project(session: Session, project_id: str) -> None:
    suite_ids = session.exec(select(Suite.id).where(Suite.project_id == project_id)).all()
    if not suite_ids:
        return
    run_ids = session.exec(select(Run.id).where(Run.suite_id.in_(suite_ids))).all()
    if run_ids:
        result_ids = session.exec(select(Result.id).where(Result.run_id.in_(run_ids))).all()
        if result_ids:
            for span in session.exec(select(Span).where(Span.result_id.in_(result_ids))).all():
                session.delete(span)
            for result in session.exec(select(Result).where(Result.id.in_(result_ids))).all():
                session.delete(result)
        for run in session.exec(select(Run).where(Run.id.in_(run_ids))).all():
            session.delete(run)
    for case in session.exec(select(TestCase).where(TestCase.suite_id.in_(suite_ids))).all():
        session.delete(case)
    for suite in session.exec(select(Suite).where(Suite.project_id == project_id)).all():
        session.delete(suite)
    session.commit()


def seed(session: Session) -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    project = session.get(Project, DEMO_PROJECT_ID)
    if project is None:
        project = Project(id=DEMO_PROJECT_ID, name=DEMO_PROJECT_NAME)
        session.add(project)
        session.commit()
    else:
        _wipe_project(session, DEMO_PROJECT_ID)

    for suite_data in data["suites"]:
        suite = Suite(
            id=suite_data["id"],
            project_id=DEMO_PROJECT_ID,
            prefix=suite_data["prefix"],
            name=suite_data["name"],
            description=suite_data.get("description", ""),
            pipeline=suite_data["pipeline"],
            sla_ms=suite_data["slaMs"],
            system_prompt=suite_data.get("systemPrompt", ""),
            context=suite_data.get("context"),
            created_at=suite_data["createdAt"],
        )
        session.add(suite)

        for case_data in suite_data["cases"]:
            session.add(
                TestCase(
                    id=case_data["id"],
                    suite_id=suite.id,
                    tag=case_data.get("tag", ""),
                    input=case_data["input"],
                    expected=case_data.get("expected", ""),
                    checks=case_data.get("checks", []),
                    recorded=case_data.get("recorded"),
                    recorded_latency_ms=case_data.get("recordedLatencyMs"),
                )
            )

    for run_data in data["runs"]:
        run = Run(
            id=run_data["id"],
            suite_id=run_data["suiteId"],
            version=run_data.get("version", ""),
            model=run_data.get("model", ""),
            target=run_data.get("target", "simulated"),
            note=run_data.get("note", ""),
            started_at=run_data["startedAt"],
            finished_at=run_data.get("finishedAt"),
            sla_ms=run_data["slaMs"],
        )
        session.add(run)
        session.flush()

        for result_data in run_data["results"]:
            result = Result(
                run_id=run.id,
                case_id=result_data["caseId"],
                input=result_data.get("input", ""),
                expected=result_data.get("expected", ""),
                actual=result_data.get("actual", ""),
                verdict=result_data["verdict"],
                category=result_data.get("category", ""),
                reason=result_data.get("reason", ""),
                checks=result_data.get("checks", []),
                latency_ms=result_data.get("latencyMs", 0),
                timestamp=result_data["timestamp"],
                model=result_data.get("model", ""),
                version=result_data.get("version", ""),
            )
            session.add(result)
            session.flush()

            for span_data in result_data.get("spans", []):
                session.add(
                    Span(
                        result_id=result.id,
                        name=span_data["name"],
                        kind=span_data.get("kind", "other"),
                        start=span_data.get("start", 0),
                        dur=span_data.get("dur", 0),
                        depth=span_data.get("depth", 0),
                        attrs=span_data.get("attrs", {}),
                    )
                )

    session.commit()


def main() -> None:
    init_db()
    with Session(engine) as session:
        seed(session)
    print(f"Seeded project '{DEMO_PROJECT_ID}' from {DATA_PATH}")


if __name__ == "__main__":
    main()
