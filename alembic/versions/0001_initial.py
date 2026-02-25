"""Initial migration - create all tables

Revision ID: 0001
Revises: 
Create Date: 2026-01-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('version', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    op.create_index(op.f('ix_user_id'), 'conversations', ['user_id'], unique=False)

    # Create conversation_messages table
    op.create_table(
        'conversation_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_message_id', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_messages_conversation_id_conversations'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_messages'))
    )
    op.create_index(op.f('ix_conversation_messages_conversation_id'), 'conversation_messages', ['conversation_id'], unique=False)

    # Create proposals table
    op.create_table(
        'proposals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('ops', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('resolution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_proposals_conversation_id_conversations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['conversation_messages.id'], name=op.f('fk_proposals_message_id_conversation_messages'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_proposals'))
    )
    op.create_index(op.f('ix_proposals_conversation_id'), 'proposals', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_proposals_status'), 'proposals', ['status'], unique=False)

    # Create tasks table
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source_message_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_tasks_conversation_id_conversations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_message_id'], ['conversation_messages.id'], name=op.f('fk_tasks_source_message_id_conversation_messages'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks'))
    )
    op.create_index(op.f('ix_tasks_conversation_id'), 'tasks', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)

    # Create task_events table
    op.create_table(
        'task_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_task_events_conversation_id_conversations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], name=op.f('fk_task_events_proposal_id_proposals'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_events_task_id_tasks'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_task_events'))
    )
    op.create_index(op.f('ix_task_events_conversation_id'), 'task_events', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_task_events_task_id'), 'task_events', ['task_id'], unique=False)

    # Create task_aliases table
    op.create_table(
        'task_aliases',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alias', sa.String(length=500), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_aliases_task_id_tasks'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_task_aliases'))
    )
    op.create_index(op.f('ix_task_aliases_alias'), 'task_aliases', ['alias'], unique=False)
    op.create_index(op.f('ix_task_aliases_task_id'), 'task_aliases', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_aliases_task_id'), table_name='task_aliases')
    op.drop_index(op.f('ix_task_aliases_alias'), table_name='task_aliases')
    op.drop_table('task_aliases')
    op.drop_index(op.f('ix_task_events_task_id'), table_name='task_events')
    op.drop_index(op.f('ix_task_events_conversation_id'), table_name='task_events')
    op.drop_table('task_events')
    op.drop_index(op.f('ix_tasks_status'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_conversation_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_proposals_status'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_conversation_id'), table_name='proposals')
    op.drop_table('proposals')
    op.drop_index(op.f('ix_conversation_messages_conversation_id'), table_name='conversation_messages')
    op.drop_table('conversation_messages')
    op.drop_index(op.f('ix_user_id'), table_name='conversations')
    op.drop_table('conversations')
