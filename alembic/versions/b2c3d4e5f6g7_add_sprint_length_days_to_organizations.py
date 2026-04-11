"""add sprint_length_days to organizations

Revision ID: b2c3d4e5f6g7
Revises: 6d7e8f9a0b1c
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6g7'
down_revision = '6d7e8f9a0b1c'
branch_labels = None
depends_on = None


def upgrade():
    # Add sprint_length_days to organizations (nullable, default 14 для новых записей)
    op.add_column(
        'organizations',
        sa.Column(
            'sprint_length_days',
            sa.Integer(),
            nullable=True,
            server_default='14',
            comment='Длительность спринта в днях (по умолчанию 14)'
        )
    )


def downgrade():
    op.drop_column('organizations', 'sprint_length_days')
