"""Add publications.citedby_url.

Stores each publication's Google Scholar "Cited by" page URL so the UI can link to
the full citation list (the in-app hover only previews the newest few).

Revision ID: 004
Revises: 003
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('publications', sa.Column('citedby_url', sa.String(1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('publications') as batch_op:
        batch_op.drop_column('citedby_url')
