from fastapi import FastAPI

from .db import init_db
from .routers import cases, runs, suites

app = FastAPI(title="Eval Workbench API")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(suites.router)
app.include_router(cases.router)
app.include_router(runs.router)
