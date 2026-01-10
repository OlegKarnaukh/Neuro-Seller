"""Change plan column from enum to string

Revision ID: 002
Revises: 001
Create Date: 2026-01-10

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Изменяем тип поля plan с ENUM на VARCHAR
    op.execute("ALTER TABLE users ALTER COLUMN plan TYPE VARCHAR USING plan::VARCHAR")
    op.execute("DROP TYPE IF EXISTS plantype")


def downgrade() -> None:
    # Откатываем изменения
    op.execute("CREATE TYPE plantype AS ENUM ('free', 'pro', 'enterprise')")
    op.execute("ALTER TABLE users ALTER COLUMN plan TYPE plantype USING plan::plantype")
