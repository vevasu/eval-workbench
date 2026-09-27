from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import os

from .db import init_db
from .routers import access, admin, cases, dev, ingest, production, reviews, runs, settings, state, suites
from .settings import is_production

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

PROD = is_production()
# In production the interactive API docs are off.
app = FastAPI(title="Eval Workbench API", docs_url=None if PROD else "/docs", redoc_url=None,
              openapi_url=None if PROD else "/openapi.json")
# Keys travel in the Authorization header, not cookies, so any origin can be allowed.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.on_event("startup")
def on_startup() -> None:
    if PROD and not os.environ.get("EVAL_WORKBENCH_ADMIN_KEY"):
        raise RuntimeError("EVAL_WORKBENCH_ADMIN_KEY must be set when EVAL_WORKBENCH_ENV=production.")
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(admin.router)
app.include_router(access.router)
app.include_router(access.admin)
app.include_router(suites.router)
app.include_router(cases.router)
app.include_router(runs.router)
app.include_router(state.router)
app.include_router(ingest.router)
app.include_router(production.router)
app.include_router(reviews.router)
app.include_router(settings.router)
app.include_router(dev.router)

# Serve the web app from the same process. Mounted last so API routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
