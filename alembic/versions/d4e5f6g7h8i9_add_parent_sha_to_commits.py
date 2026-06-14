"""add parent_sha to commits

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-04-12

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'commits',
        sa.Column('parent_sha', sa.Text(), nullable=True)
    )


def downgrade():
    op.drop_column('commits', 'parent_sha')
