from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import admin, cases, dev, ingest, runs, state, suites

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="Eval Workbench API")
# Keys travel in the Authorization header, not cookies, so any origin can be allowed.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(admin.router)
app.include_router(suites.router)
app.include_router(cases.router)
app.include_router(runs.router)
app.include_router(state.router)
app.include_router(ingest.router)
app.include_router(dev.router)

# Serve the web app from the same process. Mounted last so API routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
