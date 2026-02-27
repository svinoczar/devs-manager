"""add email_verification_codes table

Revision ID: 3a4b5c6d7e8f
Revises: 24297b8c2b28
Create Date: 2026-02-26 11:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '3a4b5c6d7e8f'
down_revision = '24297b8c2b28'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_verification_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=6), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('verified', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_verification_codes_email'), 'email_verification_codes', ['email'])
    op.create_index(op.f('ix_email_verification_codes_code'), 'email_verification_codes', ['code'])


def downgrade():
    op.drop_index(op.f('ix_email_verification_codes_code'), table_name='email_verification_codes')
    op.drop_index(op.f('ix_email_verification_codes_email'), table_name='email_verification_codes')
    op.drop_table('email_verification_codes')
