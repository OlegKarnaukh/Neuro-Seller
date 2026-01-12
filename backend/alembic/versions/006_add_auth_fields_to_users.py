"""add auth fields to users

Revision ID: 006
Revises: 005
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    # Email уже существует из миграции 003, только добавляем новые поля
    op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))
    op.add_column('users', sa.Column('tokens_limit', sa.Integer(), nullable=False, server_default='60'))
    op.add_column('users', sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'))

    # Create unique index on email
    op.create_index('ix_users_email', 'users', ['email'], unique=True)


def downgrade():
    # Drop index and columns (не трогаем email - он из миграции 003)
    op.drop_index('ix_users_email', table_name='users')
    op.drop_column('users', 'tokens_used')
    op.drop_column('users', 'tokens_limit')
    op.drop_column('users', 'password_hash')
