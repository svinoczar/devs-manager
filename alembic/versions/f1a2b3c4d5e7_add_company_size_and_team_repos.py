"""add company_size to organizations and team_id to repositories

Revision ID: f1a2b3c4d5e7
Revises: e1a2b3c4d5e6
Create Date: 2026-02-17

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e7'
down_revision = 'e1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # Create company_size enum
    op.execute("CREATE TYPE company_size_enum AS ENUM ('big', 'middle', 'small')")

    # Add company_size to organizations (default 'big' for existing rows)
    op.add_column(
        'organizations',
        sa.Column(
            'company_size',
            sa.Enum('big', 'middle', 'small', name='company_size_enum'),
            nullable=False,
            server_default='big',
        )
    )

    # Make repositories.project_id nullable (was NOT NULL before)
    op.alter_column('repositories', 'project_id', nullable=True)

    # Add team_id FK to repositories
    op.add_column(
        'repositories',
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=True)
    )


def downgrade():
    op.drop_column('repositories', 'team_id')
    op.alter_column('repositories', 'project_id', nullable=False)
    op.drop_column('organizations', 'company_size')
    op.execute("DROP TYPE company_size_enum")
