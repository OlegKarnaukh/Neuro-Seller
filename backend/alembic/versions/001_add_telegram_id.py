"""Add telegram_id to users table

Revision ID: 001
Revises: 
Create Date: 2026-01-10

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле telegram_id
    op.add_column('users', sa.Column('telegram_id', sa.String(), nullable=True))
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=False)


def downgrade() -> None:
    # Откатываем изменения
    op.drop_index('ix_users_telegram_id', table_name='users')
    op.drop_column('users', 'telegram_id')
