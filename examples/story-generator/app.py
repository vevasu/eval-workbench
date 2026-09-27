import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from story import KeyRejected, StoryError, generate_story, server_key

try:
    from eval_workbench import Client
except ImportError:  # tracing is optional
    Client = None

BASE = Path(__file__).parent
app = FastAPI(title="Story generator")

# Live traffic is sent to Eval Workbench when EVAL_WORKBENCH_API_KEY is set. Each story is scored by these checks.
LIVE_SUITE_ID = "story-generator-live"
LIVE_SUITE_NAME = "Story generator (live)"
LIVE_CHECKS = [
    {"type": "not_contains", "values": ["…"], "category": "Incomplete answer"},
    {"type": "regex", "pattern": "^\\s*(\\S+\\s+){0,79}\\S+\\s*$", "category": "Instruction not followed"},
]
workbench = Client() if Client and os.environ.get("EVAL_WORKBENCH_API_KEY") else None
# Cloud Run pauses the CPU once a response is sent, which would freeze the trace upload running in the background.
# There (K_SERVICE is set by Cloud Run), wait for the upload before replying.
ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))


class StoryRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=300)
    genre: str = Field(default="any", max_length=40)
    session_id: Optional[str] = Field(default=None, max_length=64, alias="sessionId")  # one per browser tab


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.get("/api/config")
def config():
    """Tells the page whether visitors must enter their own OpenAI key, and whether stories are monitored."""
    return {"needsKey": not server_key(), "tracing": workbench is not None}


@app.post("/api/story")
def generate(req: StoryRequest, openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key")):
    # The visitor's key is used for this one OpenAI call only. It is never stored, logged or sent to the Workbench.
    key = (openai_key or "").strip()
    if len(key) > 300:
        raise HTTPException(status_code=400, detail="That doesn't look like an OpenAI API key.")
    if not key and not server_key():
        raise HTTPException(status_code=400, detail="Enter your OpenAI API key to write a story.")

    def make(_text: str) -> str:
        return generate_story(req.prompt, req.genre, key)

    try:
        if workbench:
            text = req.prompt if req.genre == "any" else f"{req.prompt} (genre: {req.genre})"
            story = workbench.observe(LIVE_SUITE_ID, make, text, suite_name=LIVE_SUITE_NAME,
                                      version=os.environ.get("APP_VERSION", "live"), model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                                      checks=LIVE_CHECKS, session_id=req.session_id, tags=[req.genre],
                                      ignore_errors=(KeyRejected,))  # a visitor's wrong key is not a quality problem
        else:
            story = make(req.prompt)
    except StoryError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        if workbench and ON_CLOUD_RUN:
            workbench.flush(timeout=5)
    return {"story": story, "words": len(story.split())}
