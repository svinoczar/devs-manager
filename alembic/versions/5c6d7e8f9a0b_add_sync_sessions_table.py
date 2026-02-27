"""add sync_sessions table

Revision ID: 5c6d7e8f9a0b
Revises: 4b5c6d7e8f9a
Create Date: 2026-02-26 11:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '5c6d7e8f9a0b'
down_revision = '4b5c6d7e8f9a'
branch_labels = None
depends_on = None


def upgrade():
    # Create sync_status_enum type if not exists
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE sync_status_enum AS ENUM ('queued', 'running', 'completed', 'failed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create sync_sessions table using raw SQL to avoid enum recreation
    op.execute("""
        CREATE TABLE sync_sessions (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL REFERENCES teams(id),
            repository_id INTEGER NOT NULL REFERENCES repositories(id),
            status sync_status_enum NOT NULL DEFAULT 'queued',
            total_commits INTEGER NOT NULL DEFAULT 0,
            processed_commits INTEGER NOT NULL DEFAULT 0,
            new_commits INTEGER NOT NULL DEFAULT 0,
            current_phase VARCHAR(64),
            sprint_commits_done BOOLEAN NOT NULL DEFAULT false,
            errors JSON,
            result JSON,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.drop_table('sync_sessions')
    op.execute("DROP TYPE sync_status_enum")
