"""add emoji field to projects and organizations

Revision ID: 6d7e8f9a0b1c
Revises: 5c6d7e8f9a0b
Create Date: 2026-03-07

"""
from alembic import op
import sqlalchemy as sa

revision = '6d7e8f9a0b1c'
down_revision = '5c6d7e8f9a0b'
branch_labels = None
depends_on = None


def upgrade():
    # Add emoji to projects
    op.add_column(
        'projects',
        sa.Column('emoji', sa.String(10), nullable=True)
    )

    # Add emoji to organizations
    op.add_column(
        'organizations',
        sa.Column('emoji', sa.String(10), nullable=True)
    )


def downgrade():
    op.drop_column('projects', 'emoji')
    op.drop_column('organizations', 'emoji')
