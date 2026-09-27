"""human review: the reviewer's decision on a result, and when it was made

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27 03:56:37.291725
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('result', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('result', schema=None) as batch_op:
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('review')

