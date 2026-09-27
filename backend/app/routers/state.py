from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import beta
from ..auth import current_project
from ..db import get_session
from ..limits import result_count, suite_count
from ..models import Project, Run, Suite
from ..schemas import LIVE_FIELDS
from ..settings import limits
from ..serialize import run_out, suite_out

router = APIRouter(tags=["state"])


@router.get("/state")
def state(project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Everything the web app needs, in the same shape as data/sample-data.json. Production traffic is left out
    because it grows without bound; the web app reads it from /production."""
    suites = session.exec(select(Suite).where(Suite.project_id == project.id).order_by(Suite.created_at)).all()
    runs = session.exec(select(Run).where(Run.project_id == project.id, Run.target != "production")
                        .order_by(Run.started_at)).all()
    return {
        "schema": 1,
        "project": {"id": project.id, "name": project.name},
        "suites": [suite_out(session, s).model_dump(by_alias=True) for s in suites],
        "runs": [run_out(session, r, with_results=True, with_spans=True)
                 .model_dump(by_alias=True, exclude={"results": {"__all__": LIVE_FIELDS}}) for r in runs],
    }


@router.get("/usage")
def usage(project: Project = Depends(current_project), session: Session = Depends(get_session)):
    cap = limits()
    return {"executions": result_count(session, project.id), "executionsLimit": cap["max_results"],
            "suites": suite_count(session, project.id), "suitesLimit": cap["max_suites"]}


@router.delete("/project")
def delete_my_project(confirm: str = "", project: Project = Depends(current_project), session: Session = Depends(get_session)):
    """Delete everything this key's project holds, including the key itself. Cannot be undone.
    Pass ?confirm=<project id> so a stray request can't do it by accident."""
    if confirm != project.id:
        raise HTTPException(status_code=400, detail=f"To delete this project and all its data, pass confirm={project.id}.")
    return beta.delete_project(session, project.id)
