"""Unified Items migration - replace tasks with items

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-30 12:00:00.000000

This migration:
1. Creates the new items table (replaces tasks)
2. Creates the new item_events table (replaces task_events)
3. Migrates existing tasks data to items
4. Migrates existing task_events data to item_events
5. Drops old tables (tasks, task_events, task_aliases)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create items table
    op.create_table(
        'items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),  # TASK, NOTE
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='MEDIUM'),
        sa.Column('category', sa.String(length=100), nullable=False, server_default='GENERAL'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_message_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversations.id'],
            name=op.f('fk_items_conversation_id_conversations'),
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_items_user_id_users'),
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['source_message_id'], ['conversation_messages.id'],
            name=op.f('fk_items_source_message_id_conversation_messages'),
            ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_items')),
        sa.CheckConstraint("type IN ('TASK', 'NOTE')", name='ck_items_type'),
        sa.CheckConstraint("priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')", name='ck_items_priority'),
        sa.CheckConstraint("status IN ('ACTIVE', 'DONE', 'CANCELED', 'ARCHIVED')", name='ck_items_status'),
    )
    # Create indexes for items
    op.create_index('ix_items_user_id_due_at', 'items', ['user_id', 'due_at'], unique=False)
    op.create_index('ix_items_conversation_id_due_at', 'items', ['conversation_id', 'due_at'], unique=False)
    op.create_index('ix_items_user_id_status', 'items', ['user_id', 'status'], unique=False)
    op.create_index('ix_items_conversation_id_status', 'items', ['conversation_id', 'status'], unique=False)
    op.create_index('ix_items_user_id_type', 'items', ['user_id', 'type'], unique=False)
    op.create_index('ix_items_due_at_not_null', 'items', ['due_at'], unique=False, postgresql_where=sa.text('due_at IS NOT NULL'))

    # 2. Create item_events table
    op.create_table(
        'item_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversations.id'],
            name=op.f('fk_item_events_conversation_id_conversations'),
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['item_id'], ['items.id'],
            name=op.f('fk_item_events_item_id_items'),
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['proposal_id'], ['proposals.id'],
            name=op.f('fk_item_events_proposal_id_proposals'),
            ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_item_events')),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'UPDATED', 'DELETED', 'CANCELED', 'DONE', 'RESCHEDULED', 'ARCHIVED', 'UNARCHIVED', 'PINNED', 'UNPINNED')",
            name='ck_item_events_event_type'
        ),
    )
    # Create indexes for item_events
    op.create_index('ix_item_events_item_id_created_at', 'item_events', ['item_id', sa.text('created_at DESC')], unique=False)
    op.create_index('ix_item_events_conversation_id_created_at', 'item_events', ['conversation_id', sa.text('created_at DESC')], unique=False)

    # 3. Migrate existing tasks to items
    op.execute("""
        INSERT INTO items (
            id, conversation_id, user_id, type, title, content,
            due_at, timezone, priority, category, status, pinned, tags,
            source_message_id, created_at, updated_at, deleted_at
        )
        SELECT
            t.id,
            t.conversation_id,
            c.user_id,
            'TASK',
            t.title,
            t.description,
            t.due_at,
            t.timezone,
            UPPER(t.priority),
            COALESCE(UPPER(t.category), 'GENERAL'),
            CASE
                WHEN t.status = 'active' THEN 'ACTIVE'
                WHEN t.status = 'done' THEN 'DONE'
                WHEN t.status = 'cancelled' THEN 'CANCELED'
                ELSE 'ACTIVE'
            END,
            false,
            NULL,
            t.source_message_id,
            t.created_at,
            t.updated_at,
            t.deleted_at
        FROM tasks t
        JOIN conversations c ON t.conversation_id = c.id
    """)

    # 4. Migrate existing task_events to item_events
    op.execute("""
        INSERT INTO item_events (
            id, item_id, conversation_id, proposal_id,
            event_type, before, after, created_at
        )
        SELECT
            te.id,
            te.task_id,
            te.conversation_id,
            te.proposal_id,
            CASE
                WHEN LOWER(te.event_type) = 'created' THEN 'CREATED'
                WHEN LOWER(te.event_type) = 'updated' THEN 'UPDATED'
                WHEN LOWER(te.event_type) = 'deleted' THEN 'DELETED'
                WHEN LOWER(te.event_type) = 'cancelled' THEN 'CANCELED'
                WHEN LOWER(te.event_type) = 'canceled' THEN 'CANCELED'
                WHEN LOWER(te.event_type) = 'done' THEN 'DONE'
                WHEN LOWER(te.event_type) = 'rescheduled' THEN 'RESCHEDULED'
                ELSE 'UPDATED'
            END,
            te.before,
            te.after,
            te.created_at
        FROM task_events te
        WHERE EXISTS (SELECT 1 FROM items i WHERE i.id = te.task_id)
    """)

    # 5. Drop old tables
    op.drop_index('ix_task_aliases_task_id', table_name='task_aliases')
    op.drop_index('ix_task_aliases_alias', table_name='task_aliases')
    op.drop_table('task_aliases')

    op.drop_index('ix_task_events_task_id', table_name='task_events')
    op.drop_index('ix_task_events_conversation_id', table_name='task_events')
    op.drop_table('task_events')

    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index('ix_tasks_conversation_id', table_name='tasks')
    op.drop_table('tasks')


def downgrade() -> None:
    # Recreate old tables
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
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name='fk_tasks_conversation_id_conversations', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_message_id'], ['conversation_messages.id'], name='fk_tasks_source_message_id_conversation_messages', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name='pk_tasks')
    )
    op.create_index('ix_tasks_conversation_id', 'tasks', ['conversation_id'], unique=False)
    op.create_index('ix_tasks_status', 'tasks', ['status'], unique=False)

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
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name='fk_task_events_conversation_id_conversations', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], name='fk_task_events_proposal_id_proposals', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name='fk_task_events_task_id_tasks', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_task_events')
    )
    op.create_index('ix_task_events_conversation_id', 'task_events', ['conversation_id'], unique=False)
    op.create_index('ix_task_events_task_id', 'task_events', ['task_id'], unique=False)

    op.create_table(
        'task_aliases',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alias', sa.String(length=500), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name='fk_task_aliases_task_id_tasks', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_task_aliases')
    )
    op.create_index('ix_task_aliases_alias', 'task_aliases', ['alias'], unique=False)
    op.create_index('ix_task_aliases_task_id', 'task_aliases', ['task_id'], unique=False)

    # Migrate items back to tasks (only TASK type)
    op.execute("""
        INSERT INTO tasks (
            id, conversation_id, title, description,
            due_at, timezone, priority, category, status,
            source_message_id, created_at, updated_at, deleted_at
        )
        SELECT
            id, conversation_id, title, content,
            due_at, timezone, LOWER(priority), LOWER(category),
            CASE
                WHEN status = 'ACTIVE' THEN 'active'
                WHEN status = 'DONE' THEN 'done'
                WHEN status = 'CANCELED' THEN 'cancelled'
                ELSE 'active'
            END,
            source_message_id, created_at, updated_at, deleted_at
        FROM items
        WHERE type = 'TASK'
    """)

    # Migrate item_events back to task_events
    op.execute("""
        INSERT INTO task_events (
            id, task_id, conversation_id, proposal_id,
            event_type, before, after, created_at
        )
        SELECT
            ie.id, ie.item_id, ie.conversation_id, ie.proposal_id,
            LOWER(ie.event_type), ie.before, ie.after, ie.created_at
        FROM item_events ie
        JOIN items i ON ie.item_id = i.id
        WHERE i.type = 'TASK'
    """)

    # Drop new tables
    op.drop_index('ix_item_events_conversation_id_created_at', table_name='item_events')
    op.drop_index('ix_item_events_item_id_created_at', table_name='item_events')
    op.drop_table('item_events')

    op.drop_index('ix_items_due_at_not_null', table_name='items')
    op.drop_index('ix_items_user_id_type', table_name='items')
    op.drop_index('ix_items_conversation_id_status', table_name='items')
    op.drop_index('ix_items_user_id_status', table_name='items')
    op.drop_index('ix_items_conversation_id_due_at', table_name='items')
    op.drop_index('ix_items_user_id_due_at', table_name='items')
    op.drop_table('items')
