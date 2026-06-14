"""Add app_settings key/value table.

Stores user-adjustable settings (e.g. citing-paper fetching on/off, browser-connected
state) in the DB, since the frozen desktop app has no user-writable config file.

Revision ID: 003
Revises: 002
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
