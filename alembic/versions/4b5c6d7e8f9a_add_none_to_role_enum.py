"""add NONE to role enum

Revision ID: 4b5c6d7e8f9a
Revises: 3a4b5c6d7e8f
Create Date: 2026-02-26 11:45:00.000000

"""
from alembic import op


revision = '4b5c6d7e8f9a'
down_revision = '3a4b5c6d7e8f'
branch_labels = None
depends_on = None


def upgrade():
    # Add NONE value to role enum
    op.execute("ALTER TYPE role ADD VALUE 'NONE'")


def downgrade():
    # Note: PostgreSQL doesn't support removing enum values
    # You would need to recreate the enum type to remove a value
    pass
