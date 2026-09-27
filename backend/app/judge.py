"""The AI judge: asks a model whether an answer meets the criteria of an `llm_judge` check, using the project's own
model key. Checks start as pending (see decide() in scoring.py); this module fills them in and decides again.

Test runs are judged while their results are uploaded. Production requests are judged in a background thread right
after they are stored, so the application never waits for the model; anything left pending (for example if the
server restarted) is picked up by the next request that is judged.
"""
import copy
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from sqlmodel import Session, select

from .keystore import unseal
from .models import Project, Result, Run, now_ms
from .scoring import decide

log = logging.getLogger("uvicorn.error")
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TEXT = 8000  # characters of the input and output sent to the model
STALE_MS = 2 * 60 * 1000  # pending this long means its first attempt was lost

SYSTEM_PROMPT = (
    "You check answers from an AI application against criteria written by its developers. "
    "Read what the user sent, the application's answer and the criteria. Decide whether the answer meets the criteria. "
    'Reply with JSON only: {"pass": true or false, "reason": "one short sentence saying why"}.'
)


class JudgeError(Exception):
    pass


def base_url() -> str:
    # Set by the server operator only (tests point it at a stand-in), never by a request: it receives the key.
    return os.environ.get("EVAL_WORKBENCH_JUDGE_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def ask(api_key: str, model: str, criteria: str, input_text: str, output: str) -> dict:
    """One judgment: {"pass": bool, "reason": str}. Raises JudgeError with a readable message."""
    user = (f"Criteria:\n{criteria}\n\nWhat the user sent:\n{input_text[:MAX_TEXT]}\n\n"
            f"The application's answer:\n{output[:MAX_TEXT] or '(empty)'}")
    body = {"model": model or DEFAULT_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]}
    req = urllib.request.Request(base_url() + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise JudgeError("the model provider rejected the saved key") from None
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise JudgeError(f"the model provider returned an error ({e.code}){': ' + detail if detail else ''}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise JudgeError(f"could not reach the model provider ({getattr(e, 'reason', e)})") from None
    try:
        verdict = json.loads(data["choices"][0]["message"]["content"])
        return {"pass": bool(verdict["pass"]), "reason": str(verdict.get("reason") or "").strip()[:500]}
    except (KeyError, IndexError, TypeError, ValueError):
        raise JudgeError("the model's reply was not the expected JSON") from None


def _pending(checks: list) -> list:
    return [c for c in checks if c.get("type") == "llm_judge" and c.get("pending")]


def judge_rows(session: Session, project: Project, rows: list) -> None:
    """Judge the pending checks of these results (in parallel), decide again and save. Commits."""
    key = unseal(project.judge_key)
    model = project.judge_model or DEFAULT_MODEL
    # Work on copies: the database only notices a JSON column changed if it gets a new value, not an edited one.
    copies = {row.id: copy.deepcopy(row.checks or []) for row in rows}
    work = [(row, c) for row in rows for c in _pending(copies[row.id])]
    if not work:
        return

    def one(item):
        _, check = item
        if not key:
            return JudgeError("no model key is saved for the AI judge. Add one on the Production page")
        try:
            return ask(key, model, check["spec"], item[0].input, item[0].actual)
        except JudgeError as e:
            return e

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(one, work))
    runs = {}
    for (row, check), answer in zip(work, answers):
        check.pop("pending", None)
        if isinstance(answer, JudgeError):  # a person decides instead
            check.update({"pass": None, "manual": True, "detail": f"The AI judge could not run: {answer}."})
        else:
            check.update({"pass": answer["pass"], "detail": answer["reason"] or ("Meets the criteria" if answer["pass"] else "Does not meet the criteria"),
                          "judgedBy": model})
    for row in {id(r): r for r, _ in work}.values():
        run = runs.get(row.run_id) or session.get(Run, (row.project_id, row.run_id))
        runs[row.run_id] = run
        checks = copies[row.id]
        refusal = any(c.get("refusalExpected") for c in checks)
        for c in checks:
            c.pop("refusalExpected", None)
        ev = decide(checks, row.actual, row.latency_ms, run.sla_ms if run else None, live=run is not None and run.target == "production",
                    refusal_expected=refusal)
        row.checks = ev["checks"]
        if row.review:  # a person already decided: keep their verdict, update the automatic one underneath
            row.review = {**row.review, "autoVerdict": ev["verdict"], "autoCategory": ev["category"]}
        else:
            row.verdict, row.category = ev["verdict"], ev["category"]
        row.reason = ev["reason"]
        session.add(row)
    session.commit()


def judge_later(engine, project_id: str, result_ids: list) -> None:
    """Judge production requests in a background thread, plus any left pending earlier in the project."""
    def work():
        try:
            with Session(engine) as session:
                project = session.get(Project, project_id)
                if project is None:
                    return
                rows = session.exec(select(Result).where(Result.project_id == project_id, Result.id.in_(result_ids))).all()
                stale = session.exec(select(Result).where(
                    Result.project_id == project_id, Result.category == "Awaiting AI judge",
                    Result.timestamp < now_ms() - STALE_MS, Result.id.not_in(result_ids)).limit(10)).all()
                judge_rows(session, project, list(rows) + list(stale))
        except Exception:  # noqa: BLE001 - judging must never take the server down
            log.exception("AI judge failed for project %s", project_id)

    threading.Thread(target=work, daemon=True).start()


def needs_judge(ev: dict) -> bool:
    return ev.get("category") == "Awaiting AI judge"

