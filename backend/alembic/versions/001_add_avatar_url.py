"""Add avatar_url to agents table

Revision ID: 001_add_avatar_url
Revises: 
Create Date: 2026-01-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '001_add_avatar_url'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """
    Добавляет поле avatar_url в таблицу agents
    """
    op.add_column('agents', sa.Column('avatar_url', sa.Text(), nullable=True))
    print("✅ Поле avatar_url добавлено в таблицу agents")


def downgrade():
    """
    Откат миграции (удаляет поле avatar_url)
    """
    op.drop_column('agents', 'avatar_url')
    print("⬇️ Поле avatar_url удалено из таблицы agents")
