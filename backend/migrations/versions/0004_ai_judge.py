"""ai judge: checks on live traffic per suite, and each project's encrypted model key and judge model

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27 04:49:00.989800
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.add_column(sa.Column('judge_key', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('judge_model', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))  # existing projects get ''

    with op.batch_alter_table('suite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('live_checks', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('suite', schema=None) as batch_op:
        batch_op.drop_column('live_checks')

    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_column('judge_model')
        batch_op.drop_column('judge_key')

