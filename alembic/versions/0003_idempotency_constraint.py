"""Add unique constraint for client_message_id idempotency

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Clean up existing duplicates by setting client_message_id to NULL
    # for all but the earliest message in each (conversation_id, client_message_id) group.
    # This preserves the first message with each client_message_id.
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE conversation_messages
        SET client_message_id = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY conversation_id, client_message_id
                           ORDER BY created_at ASC
                       ) as rn
                FROM conversation_messages
                WHERE client_message_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """))

    # Step 2: Add unique constraint on (conversation_id, client_message_id)
    # PostgreSQL allows multiple NULLs in unique constraints, so this only
    # enforces uniqueness when client_message_id is provided.
    op.create_unique_constraint(
        'uq_conversation_messages_conversation_client_msg',
        'conversation_messages',
        ['conversation_id', 'client_message_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_conversation_messages_conversation_client_msg',
        'conversation_messages',
        type_='unique',
    )
