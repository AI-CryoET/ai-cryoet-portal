"""add mrc_voxel_size_missing to tomogram tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-07 00:00:00.000000

Flags a tomogram whose MRC header carries no voxel size (cella=0). mrc-ng-server
then advertises a bogus 1 Angstrom default resolution, so the Neuroglancer viewer
renders the volume ~10x too small and any bbox annotation floats off it; the
frontend disables the launch button and the acquisition gets a scan warning.

The tomogram tables are pure projections of the filesystem (rebuilt every scan),
so existing rows get the ``false`` server default here and the correct value on
the next re-scan — no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ('raw_tomograms', 'post_processed_tomograms'):
        op.add_column(
            table,
            sa.Column(
                'mrc_voxel_size_missing',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ('raw_tomograms', 'post_processed_tomograms'):
        op.drop_column(table, 'mrc_voxel_size_missing')
