"""Project settings: the AI judge's model key and model, and the checks that run on every production request."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..auth import current_project
from ..db import get_session
from ..judge import DEFAULT_MODEL, JudgeError, ask
from ..keystore import hint, seal, unseal
from ..models import Project
from ..schemas import JudgeSettingsIn, LiveChecksIn
from ..services import get_suite_or_404, validate_checks

router = APIRouter(tags=["settings"])


def _judge_out(project: Project) -> dict:
    key = unseal(project.judge_key)
    return {"configured": bool(key), "provider": "openai", "model": project.judge_model or DEFAULT_MODEL,
            "keyHint": hint(key) if key else None, "unreadable": bool(project.judge_key) and not key}


@router.get("/settings/judge")
def get_judge(project: Project = Depends(current_project)):
    """Whether the AI judge has a model key. The key itself is never returned."""
    return _judge_out(project)


@router.put("/settings/judge")
def set_judge(body: JudgeSettingsIn, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    if body.api_key is not None:
        key = body.api_key.strip()
        if not key:
            raise HTTPException(status_code=422, detail="Enter a model key, or remove the saved one.")
        project.judge_key = seal(key)
    if body.model is not None:
        project.judge_model = body.model.strip()
    session.add(project)
    session.commit()
    return _judge_out(project)


@router.delete("/settings/judge")
def remove_judge_key(project: Project = Depends(current_project), session: Session = Depends(get_session)):
    project.judge_key = None
    session.add(project)
    session.commit()
    return _judge_out(project)


@router.post("/settings/judge/test")
def test_judge(project: Project = Depends(current_project)):
    """Ask the model one small question with the saved key, to show whether the AI judge will work."""
    key = unseal(project.judge_key)
    if not key:
        raise HTTPException(status_code=400, detail="Save a model key first.")
    try:
        answer = ask(key, project.judge_model or DEFAULT_MODEL, "The answer greets the user.", "Say hello", "Hello there!")
    except JudgeError as e:
        return {"ok": False, "message": f"The AI judge could not run: {e}."}
    return {"ok": True, "message": f"The AI judge works. It judged a test answer: {'pass' if answer['pass'] else 'fail'}."}


@router.get("/suites/{suite_id}/live-checks")
def get_live_checks(suite_id: str, project: Project = Depends(current_project), session: Session = Depends(get_session)):
    return {"checks": get_suite_or_404(session, project.id, suite_id).live_checks or []}


@router.put("/suites/{suite_id}/live-checks")
def set_live_checks(suite_id: str, body: LiveChecksIn, project: Project = Depends(current_project),
                    session: Session = Depends(get_session)):
    """Checks run on every production request of this suite, in addition to those the application sends."""
    suite = get_suite_or_404(session, project.id, suite_id)
    validate_checks(body.checks)
    suite.live_checks = body.checks or None
    session.add(suite)
    session.commit()
    return {"checks": suite.live_checks or []}
