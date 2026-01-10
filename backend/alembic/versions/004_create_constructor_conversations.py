"""Create constructor_conversations table

Revision ID: 004
Revises: 003
Create Date: 2026-01-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'constructor_conversations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('messages', JSONB, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    
    # Индекс для быстрого поиска по user_id
    op.create_index('ix_constructor_conversations_user_id', 'constructor_conversations', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_constructor_conversations_user_id', table_name='constructor_conversations')
    op.drop_table('constructor_conversations')
