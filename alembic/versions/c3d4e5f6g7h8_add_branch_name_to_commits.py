"""add branch_name to commits

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-12

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'commits',
        sa.Column('branch_name', sa.String(128), nullable=True)
    )


def downgrade():
    op.drop_column('commits', 'branch_name')
