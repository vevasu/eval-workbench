from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth import current_project
from ..db import get_session
from ..models import Project, Run, Suite
from ..serialize import run_out, suite_out

router = APIRouter(tags=["state"])


@router.get("/state")
def state(project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Everything the web app needs, in the same shape as data/sample-data.json."""
    suites = session.exec(select(Suite).where(Suite.project_id == project.id).order_by(Suite.created_at)).all()
    runs = session.exec(select(Run).where(Run.project_id == project.id).order_by(Run.started_at)).all()
    return {
        "schema": 1,
        "project": {"id": project.id, "name": project.name},
        "suites": [suite_out(session, s).model_dump(by_alias=True) for s in suites],
        "runs": [run_out(session, r, with_results=True, with_spans=True).model_dump(by_alias=True) for r in runs],
    }
