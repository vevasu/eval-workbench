"""Alembic environment. Uses the app's own engine, so DATABASE_URL works the same for migrations as for the server."""
from alembic import context
from sqlalchemy import text
from sqlmodel import SQLModel

from app import models  # noqa: F401  (registers the tables on SQLModel.metadata)
from app.db import engine

target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
        with context.begin_transaction():
            if connection.dialect.name == "postgresql":
                # Several Cloud Run instances can start at once; only one migrates at a time. A transaction-level
                # lock is released at commit, so it also works through Neon's transaction-mode connection pooler.
                connection.execute(text("SELECT pg_advisory_xact_lock(7231850)"))
            context.run_migrations()


run_migrations_online()
