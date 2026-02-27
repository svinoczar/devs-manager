"""add pull_requests and issues tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e7
Create Date: 2026-02-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pull_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('contributor_id', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.Integer(), nullable=True),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('author_login', sa.String(length=128), nullable=True),
        sa.Column('author_avatar', sa.Text(), nullable=True),
        sa.Column('pr_created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('pr_closed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('pr_merged_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contributor_id'], ['contributors.id']),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('contributor_id', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.Integer(), nullable=True),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('author_login', sa.String(length=128), nullable=True),
        sa.Column('author_avatar', sa.Text(), nullable=True),
        sa.Column('issue_created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('issue_closed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contributor_id'], ['contributors.id']),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('issues')
    op.drop_table('pull_requests')
