"""add preview_path to md_runs

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-07 00:00:00.000000

Cache-relative path of the OVITO preview PNG the scanner renders for each MD
run (``{sample_id}/{md_run_id}.png`` under $CATALOG_MD_PREVIEW_DIR), served by
the API's /md-previews route. DB-only — not authored in md_run.toml, set by the
scanner's ``--md-preview-dir`` generation.

``md_runs`` is a filesystem projection (rebuilt every scan), so existing rows
get NULL here and the correct value on the next scan that has previews enabled —
no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('md_runs', sa.Column('preview_path', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('md_runs', 'preview_path')
