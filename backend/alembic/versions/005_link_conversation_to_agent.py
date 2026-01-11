"""Link conversation to agent

Revision ID: 005
Revises: 004
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле в constructor_conversations
    op.add_column('constructor_conversations', 
        sa.Column('created_agent_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # Добавляем поле в agents
    op.add_column('agents', 
        sa.Column('constructor_conversation_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # Создаём индексы для быстрого поиска
    op.create_index('ix_constructor_conversations_created_agent_id', 
                    'constructor_conversations', ['created_agent_id'])
    op.create_index('ix_agents_constructor_conversation_id', 
                    'agents', ['constructor_conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_agents_constructor_conversation_id', table_name='agents')
    op.drop_index('ix_constructor_conversations_created_agent_id', 
                  table_name='constructor_conversations')
    op.drop_column('agents', 'constructor_conversation_id')
    op.drop_column('constructor_conversations', 'created_agent_id')
