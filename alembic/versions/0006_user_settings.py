"""Add user timezone, metas, user_metas, and user_options tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-02-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user settings infrastructure.

    - Add timezone column to users table
    - Create metas catalog table
    - Create user_metas pivot table
    - Create user_options table
    """
    # 1. Add timezone column to users
    op.add_column(
        'users',
        sa.Column('timezone', sa.String(length=64), nullable=True),
    )

    # 2. Create metas catalog table
    op.create_table(
        'metas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False, server_default='flag'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_metas')),
        sa.UniqueConstraint('key', name=op.f('uq_metas_key')),
    )

    # 3. Create user_metas pivot table
    op.create_table(
        'user_metas',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('meta_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_user_metas_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['meta_id'],
            ['metas.id'],
            name=op.f('fk_user_metas_meta_id_metas'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('user_id', 'meta_id', name=op.f('pk_user_metas')),
    )
    op.create_index(
        op.f('ix_user_metas_user_id'), 'user_metas', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_user_metas_meta_id'), 'user_metas', ['meta_id'], unique=False
    )

    # 4. Create user_options table
    op.create_table(
        'user_options',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'settings_json',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_user_options_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_options')),
    )


def downgrade() -> None:
    """Remove user settings infrastructure."""
    op.drop_table('user_options')
    op.drop_index(op.f('ix_user_metas_meta_id'), table_name='user_metas')
    op.drop_index(op.f('ix_user_metas_user_id'), table_name='user_metas')
    op.drop_table('user_metas')
    op.drop_table('metas')
    op.drop_column('users', 'timezone')
