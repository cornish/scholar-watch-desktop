"""Remove User, UserScholar tables and notifications.user_id column.

Revision ID: 001
Revises:
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop user-related tables
    op.drop_table('user_scholars')
    op.drop_table('users')

    # Remove user_id column from notifications
    # SQLite doesn't support DROP COLUMN natively before 3.35.0,
    # so we use batch mode for compatibility
    with op.batch_alter_table('notifications') as batch_op:
        batch_op.drop_column('user_id')


def downgrade() -> None:
    # Re-add user_id to notifications
    with op.batch_alter_table('notifications') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))

    # Recreate users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # Recreate user_scholars table
    op.create_table(
        'user_scholars',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('researcher_id', sa.Integer(), sa.ForeignKey('researchers.id'), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('notify_new_publications', sa.Boolean(), default=True, nullable=False),
        sa.Column('notify_citation_milestones', sa.Boolean(), default=True, nullable=False),
        sa.Column('notify_h_index_change', sa.Boolean(), default=True, nullable=False),
        sa.UniqueConstraint('user_id', 'researcher_id', name='uq_user_researcher'),
    )
