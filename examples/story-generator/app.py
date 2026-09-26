import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from story import StoryError, generate_story

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


class StoryRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=300)
    genre: str = Field(default="any", max_length=40)


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.post("/api/story")
def generate(req: StoryRequest):
    def make(_text: str) -> str:
        return generate_story(req.prompt, req.genre)

    try:
        if workbench:
            text = req.prompt if req.genre == "any" else f"{req.prompt} (genre: {req.genre})"
            story = workbench.observe(LIVE_SUITE_ID, make, text, suite_name=LIVE_SUITE_NAME,
                                      version="live", model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), checks=LIVE_CHECKS)
        else:
            story = make(req.prompt)
    except StoryError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"story": story, "words": len(story.split())}
