"""add is_active to user_sessions

Revision ID: d500d7d5d52d
Revises: c03ea255ac26
Create Date: 2026-02-17 01:23:06.583596

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd500d7d5d52d'
down_revision = 'c03ea255ac26'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('user_sessions', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))


def downgrade():
    op.drop_column('user_sessions', 'is_active')
