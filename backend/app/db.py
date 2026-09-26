import os
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

def _normalize(url: str) -> str:
    """Accept a Postgres address as hosts show it (postgres:// or postgresql://) and use the psycopg driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# Any SQLAlchemy URL works, so Postgres can replace SQLite by setting DATABASE_URL.
DATABASE_URL = _normalize(os.environ.get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'workbench.db'}"))
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
elif "psycopg" in DATABASE_URL:
    _connect_args = {"prepare_threshold": None}  # connection poolers such as Neon's do not keep prepared statements
else:
    _connect_args = {}
# pool_pre_ping reconnects if the database went to sleep and dropped an idle connection.
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_foreign_keys(dbapi_connection, _record):
        # SQLite ignores foreign keys by default; enforce them so local runs and tests behave like Postgres.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
