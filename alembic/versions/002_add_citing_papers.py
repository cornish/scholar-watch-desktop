"""Add citing_papers table.

Stores the individual papers that cite a tracked publication, captured when a
publication's citation count increases, so the UI can reveal *which* paper is
behind the "+N" change indicator.

Revision ID: 002
Revises: 001
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'citing_papers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('publication_id', sa.Integer(), sa.ForeignKey('publications.id'), nullable=False),
        sa.Column('first_seen_run_id', sa.Integer(), sa.ForeignKey('scrape_runs.id'), nullable=False),
        sa.Column('title', sa.String(1000), nullable=False),
        sa.Column('authors', sa.Text(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('venue', sa.String(500), nullable=True),
        sa.Column('url', sa.String(1000), nullable=True),
        sa.Column('norm_key', sa.String(255), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('publication_id', 'norm_key', name='uq_citing_pub_normkey'),
    )
    op.create_index('ix_citing_papers_publication_id', 'citing_papers', ['publication_id'])
    op.create_index('ix_citing_papers_first_seen_run_id', 'citing_papers', ['first_seen_run_id'])
    op.create_index('ix_citing_papers_norm_key', 'citing_papers', ['norm_key'])


def downgrade() -> None:
    op.drop_index('ix_citing_papers_norm_key', table_name='citing_papers')
    op.drop_index('ix_citing_papers_first_seen_run_id', table_name='citing_papers')
    op.drop_index('ix_citing_papers_publication_id', table_name='citing_papers')
    op.drop_table('citing_papers')
