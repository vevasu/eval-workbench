"""Bring the database schema up to date on startup.

A database created before migrations existed already has the baseline tables but no alembic_version table,
so it is stamped as the baseline instead of having the tables created again. Any difference left between
the models and the live schema is logged, so drift shows up in the server logs instead of as a failed query.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Integer, inspect
from sqlmodel import SQLModel

from . import models  # noqa: F401  (registers the tables that schema_drift compares against)
from .db import engine

BASELINE = "0001"
BACKEND_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("uvicorn.error")


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def upgrade() -> None:
    cfg = _config()
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "project" in tables:
        log.info("Existing database without migration history: marking it as the baseline schema.")
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
    for diff in schema_drift():
        log.warning("Database schema differs from the models: %s", diff)


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # SQLite integers are 64-bit whatever the declared type, so INTEGER vs BIGINT only matters on Postgres.
    if context.dialect.name == "sqlite" and isinstance(inspected_type, Integer) and isinstance(metadata_type, Integer):
        return False
    return None  # let Alembic decide


def schema_drift() -> list:
    with engine.connect() as connection:
        ctx = MigrationContext.configure(connection, opts={"compare_type": _compare_type})
        return compare_metadata(ctx, SQLModel.metadata)
