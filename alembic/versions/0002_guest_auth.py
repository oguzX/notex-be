"""Add guest authentication

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('client_uuid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_client_uuid'), 'users', ['client_uuid'], unique=True)

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('replaced_by_token_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens'))
    )
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)

    # Handle existing conversations by creating placeholder users
    # This ensures we don't lose data during migration
    conn = op.get_bind()
    
    # Check if there are any existing conversations
    result = conn.execute(sa.text("SELECT COUNT(*) FROM conversations"))
    conversation_count = result.scalar()
    
    if conversation_count > 0:
        # Get unique user_ids from existing conversations
        result = conn.execute(sa.text("SELECT DISTINCT user_id FROM conversations"))
        existing_user_ids = [row[0] for row in result]
        
        # Create placeholder guest users for each unique user_id
        for user_id in existing_user_ids:
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, kind, client_uuid, created_at, updated_at) "
                    "VALUES (:id, 'GUEST', NULL, now(), now())"
                ),
                {"id": user_id}
            )
        
        conn.execute(sa.text("COMMIT"))
    
    # Now safe to add foreign key constraint from conversations to users
    op.create_foreign_key(
        op.f('fk_conversations_user_id_users'),
        'conversations',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    # Drop foreign key constraint from conversations
    op.drop_constraint(op.f('fk_conversations_user_id_users'), 'conversations', type_='foreignkey')
    
    # Drop refresh_tokens table
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    
    # Drop users table
    op.drop_index(op.f('ix_users_client_uuid'), table_name='users')
    op.drop_table('users')
