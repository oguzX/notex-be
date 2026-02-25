"""Add devices table for push notifications

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create devices table for push notification registration.
    
    The notification_token field stores OneSignal player_id (subscription ID),
    which is the unique identifier for a device subscription in OneSignal.
    """
    op.create_table(
        'devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        # notification_token stores OneSignal player_id / subscription_id
        # This identifies the device in OneSignal's system
        sa.Column('notification_token', sa.String(length=255), nullable=False),
        sa.Column('device_name', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_devices_user_id_users'),
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_devices')),
        sa.UniqueConstraint(
            'user_id',
            'notification_token',
            name='uq_devices_user_id_notification_token'
        ),
    )
    
    # Index on user_id for fast lookup of user's devices
    op.create_index(
        op.f('ix_devices_user_id'),
        'devices',
        ['user_id'],
        unique=False
    )
    
    # Index on notification_token for deactivation by token
    op.create_index(
        op.f('ix_devices_notification_token'),
        'devices',
        ['notification_token'],
        unique=False
    )


def downgrade() -> None:
    """Drop devices table."""
    op.drop_index(op.f('ix_devices_notification_token'), table_name='devices')
    op.drop_index(op.f('ix_devices_user_id'), table_name='devices')
    op.drop_table('devices')
