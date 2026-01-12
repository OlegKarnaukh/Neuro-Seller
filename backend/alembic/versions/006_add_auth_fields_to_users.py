"""add auth fields to users

Revision ID: 006
Revises: 005
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(index_name: str) -> bool:
    """Check if index exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('users')]
    return index_name in indexes


def upgrade():
    # Добавляем колонки только если их нет
    if not column_exists('users', 'password_hash'):
        op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))

    if not column_exists('users', 'tokens_limit'):
        op.add_column('users', sa.Column('tokens_limit', sa.Integer(), nullable=False, server_default='60'))

    if not column_exists('users', 'tokens_used'):
        op.add_column('users', sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'))

    # Create unique index on email if not exists
    if not index_exists('ix_users_email'):
        op.create_index('ix_users_email', 'users', ['email'], unique=True)


def downgrade():
    # Drop index and columns (не трогаем email - он из миграции 003)
    op.drop_index('ix_users_email', table_name='users')
    op.drop_column('users', 'tokens_used')
    op.drop_column('users', 'tokens_limit')
    op.drop_column('users', 'password_hash')
