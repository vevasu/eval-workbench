from fastapi import APIRouter, Depends
from sqlmodel import Session, delete, select

from ..auth import current_project
from ..db import get_session
from ..models import Project, Run, Suite, TestCase
from ..schemas import ImportIn, SuiteIn, SuiteOut, SuitePatch
from ..serialize import suite_out
from ..services import add_case, create_suite, delete_runs, get_suite_or_404, parse_import

router = APIRouter(prefix="/suites", tags=["suites"])


@router.get("", response_model=list[SuiteOut])
def list_suites(project: Project = Depends(current_project), session: Session = Depends(get_session)):
    suites = session.exec(select(Suite).where(Suite.project_id == project.id).order_by(Suite.created_at)).all()
    return [suite_out(session, s, with_cases=False) for s in suites]


@router.post("", response_model=SuiteOut, status_code=201)
def create(body: SuiteIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    suite = create_suite(session, project.id, body.model_dump())
    session.commit()
    return suite_out(session, suite)


@router.post("/import", response_model=SuiteOut, status_code=201)
def import_suite(body: ImportIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    spec = parse_import(body.format, body.content, body.name)
    suite = create_suite(session, project.id, {
        "name": spec["name"], "description": spec.get("description"), "pipeline": spec.get("pipeline"),
        "sla_ms": spec.get("slaMs"), "system_prompt": spec.get("systemPrompt"), "context": spec.get("context")})
    session.flush()
    for c in spec["cases"]:
        has_actual = c.get("actual") not in (None, "")
        add_case(session, suite, {
            "id": c.get("id"), "input": str(c["input"]), "expected": str(c.get("expected") or ""), "tag": c.get("tag") or "",
            "checks": c.get("checks") or [], "recorded": str(c["actual"]) if has_actual else None,
            "recorded_latency_ms": int(c.get("latencyMs") or 0) if has_actual else None})
    session.commit()
    return suite_out(session, suite)


@router.get("/{suite_id}", response_model=SuiteOut)
def get_suite(suite_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    return suite_out(session, get_suite_or_404(session, project.id, suite_id))


@router.patch("/{suite_id}", response_model=SuiteOut)
def update_suite(suite_id: str, body: SuitePatch, project: Project = Depends(current_project),
                 session: Session = Depends(get_session)):
    suite = get_suite_or_404(session, project.id, suite_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(suite, field, value)
    session.add(suite)
    session.commit()
    return suite_out(session, suite)


@router.delete("/{suite_id}")
def delete_suite(suite_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Delete a suite with its test cases and every run of it, test runs and production traffic alike."""
    suite = get_suite_or_404(session, project.id, suite_id)
    run_ids = list(session.exec(select(Run.id).where(Run.project_id == project.id, Run.suite_id == suite.id)).all())
    results = delete_runs(session, project.id, run_ids)
    cases = session.exec(delete(TestCase).where(TestCase.project_id == project.id, TestCase.suite_id == suite.id)).rowcount
    session.delete(suite)
    session.commit()
    return {"suiteId": suite_id, "deleted": {"cases": cases, "runs": len(run_ids), "results": results}}
