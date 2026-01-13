"""Add full_name and base44_id to users

Revision ID: 007
Revises: 005
Create Date: 2026-01-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поля для синхронизации с Base44
    op.add_column('users', sa.Column('full_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('base44_id', sa.String(), nullable=True))
    op.create_index('ix_users_base44_id', 'users', ['base44_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_base44_id', table_name='users')
    op.drop_column('users', 'base44_id')
    op.drop_column('users', 'full_name')
