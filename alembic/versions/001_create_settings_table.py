"""Create settings table

Revision ID: 001
Revises:
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('value_type', sa.String(50), nullable=False, server_default='string'),
        sa.Column('category', sa.String(100), nullable=False, server_default='general'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('requires_reload', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('is_secret', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('env_fallback', sa.String(255), nullable=True),
        sa.Column('household_id', sa.String(255), nullable=True),
        sa.Column('node_id', sa.String(255), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', 'household_id', 'node_id', 'user_id', name='uq_setting_scope')
    )
    op.create_index(op.f('ix_settings_key'), 'settings', ['key'])
    op.create_index(op.f('ix_settings_category'), 'settings', ['category'])
    op.create_index(op.f('ix_settings_household_id'), 'settings', ['household_id'])
    op.create_index(op.f('ix_settings_node_id'), 'settings', ['node_id'])
    op.create_index(op.f('ix_settings_user_id'), 'settings', ['user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_settings_user_id'), table_name='settings')
    op.drop_index(op.f('ix_settings_node_id'), table_name='settings')
    op.drop_index(op.f('ix_settings_household_id'), table_name='settings')
    op.drop_index(op.f('ix_settings_category'), table_name='settings')
    op.drop_index(op.f('ix_settings_key'), table_name='settings')
    op.drop_table('settings')
