"""Web front end. Starts a run in the background and lets the page poll for each agent's progress.

    python -m uvicorn app:app --port 8200
"""
import re
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from writer_critic import config, observability
from writer_critic.llm import LLM, LLMError
from writer_critic.models import Brief
from writer_critic.pipeline import Pipeline
from writer_critic.prompts import DEFAULT_CRITERIA

BASE = Path(__file__).parent
app = FastAPI(title="Writer & Critic")
JOBS: dict = {}  # job id -> progress. In memory only; fine for a local demo.
MAX_JOBS = 50


class JobRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    audience: str = Field(default="a general audience", max_length=200)
    key_points: str = Field(default="", max_length=2000, alias="keyPoints")
    format: str = Field(default="LinkedIn post", max_length=40)
    criteria: Optional[str] = Field(default=None, max_length=1000)


def run_job(job: dict, brief: Brief) -> None:
    def on_event(event: dict) -> None:
        if event["type"] == "start":
            job["current"] = {"agent": event["agent"], "label": event["label"], "round": event["round"]}
        elif event["type"] == "step":
            job["steps"].append(event["step"])
            job["current"] = None
        elif event["type"] == "done":
            job["result"] = event["result"]

    try:
        observability.run_traced(lambda: Pipeline(LLM(), on_event=on_event).run(brief), brief)
        job["status"] = "done"
    except LLMError as e:
        job["status"], job["error"] = "error", str(e)
    except Exception as e:  # noqa: BLE001 - show any failure in the page instead of hanging
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
    job["current"] = None


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/config")
def get_config():
    return {"provider": config.PROVIDER, "model": config.MODEL, "maxRounds": config.MAX_ROUNDS,
            "approveScore": config.APPROVE_SCORE, "tracing": observability.enabled(), "defaultCriteria": DEFAULT_CRITERIA}


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if len(JOBS) >= MAX_JOBS:
        JOBS.pop(next(iter(JOBS)))
    points = [p.strip() for p in re.split(r"[;\n]", req.key_points) if p.strip()]
    brief = Brief(topic=req.topic.strip(), audience=req.audience.strip() or "a general audience", key_points=points,
                  format=req.format, criteria=(req.criteria or "").strip() or DEFAULT_CRITERIA)
    job = {"id": uuid.uuid4().hex[:10], "status": "running", "steps": [], "current": None, "result": None, "error": None}
    JOBS[job["id"]] = job
    threading.Thread(target=run_job, args=(job, brief), daemon=True).start()
    return {"id": job["id"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job
