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
    """
    Adds auth fields to users table.
    Uses try/except as fallback if column_exists checks fail.
    """
    # Add password_hash
    try:
        if not column_exists('users', 'password_hash'):
            op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))
    except Exception as e:
        print(f"Warning: Could not add password_hash column (may already exist): {e}")

    # Add tokens_limit
    try:
        if not column_exists('users', 'tokens_limit'):
            op.add_column('users', sa.Column('tokens_limit', sa.Integer(), nullable=False, server_default='60'))
    except Exception as e:
        print(f"Warning: Could not add tokens_limit column (may already exist): {e}")

    # Add tokens_used
    try:
        if not column_exists('users', 'tokens_used'):
            op.add_column('users', sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'))
    except Exception as e:
        print(f"Warning: Could not add tokens_used column (may already exist): {e}")

    # Create unique index on email if not exists
    try:
        if not index_exists('ix_users_email'):
            op.create_index('ix_users_email', 'users', ['email'], unique=True)
    except Exception as e:
        print(f"Warning: Could not create index ix_users_email (may already exist): {e}")


def downgrade():
    # Drop index and columns (не трогаем email - он из миграции 003)
    op.drop_index('ix_users_email', table_name='users')
    op.drop_column('users', 'tokens_used')
    op.drop_column('users', 'tokens_limit')
    op.drop_column('users', 'password_hash')
