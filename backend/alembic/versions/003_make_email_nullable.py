"""Make email column nullable

Revision ID: 003
Revises: 002
Create Date: 2026-01-10

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Делаем поле email nullable
    op.alter_column('users', 'email',
                    existing_type=sa.VARCHAR(),
                    nullable=True)


def downgrade() -> None:
    # Откатываем изменения
    op.alter_column('users', 'email',
                    existing_type=sa.VARCHAR(),
                    nullable=False)
