"""production trace fields: user, session, tags, metadata, tokens and cost on results; origin on test cases

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27 02:49:51.005012
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('result', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('session_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('tags', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('meta', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('tokens_in', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tokens_out', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cost_usd', sa.Float(), nullable=True))
        batch_op.create_index('ix_result_project_timestamp', ['project_id', 'timestamp'], unique=False)
        batch_op.create_index(batch_op.f('ix_result_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_result_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('testcase', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('testcase', schema=None) as batch_op:
        batch_op.drop_column('origin')

    with op.batch_alter_table('result', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_result_user_id'))
        batch_op.drop_index(batch_op.f('ix_result_session_id'))
        batch_op.drop_index('ix_result_project_timestamp')
        batch_op.drop_column('cost_usd')
        batch_op.drop_column('tokens_out')
        batch_op.drop_column('tokens_in')
        batch_op.drop_column('meta')
        batch_op.drop_column('tags')
        batch_op.drop_column('session_id')
        batch_op.drop_column('user_id')

