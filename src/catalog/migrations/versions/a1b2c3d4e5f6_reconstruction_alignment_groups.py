"""reconstruction alignment groups

Revision ID: a1b2c3d4e5f6
Revises: 72e3bbb2df2a
Create Date: 2026-07-27 00:00:00.000000

Adds the ``reconstruction_alignments`` table and folds the alignment group into
the primary key of the three leaf tables, which also lose their tilt-series /
target-tomogram columns.

The three leaf tables are pure projections of the filesystem: the scanner
rebuilds them from reconstruction.toml plus the directory walk on every run, and
nothing in them is authored in the database. No existing row records its
alignment group anywhere but its ``mrc_path``, and rows with a null path could
not be recovered at all — so they are dropped and recreated with the wider key
rather than backfilled. **Re-scan after upgrading.**

Drop/create (rather than a ``batch_alter_table`` copy) because the rows are
discarded either way: SQLite cannot ALTER a primary key, and every constraint in
this schema is unnamed, so there is nothing for batch mode to drop by name.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '72e3bbb2df2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACQ_FK = (
    ['sample_id', 'acquisition_id'],
    ['acquisitions.sample_id', 'acquisitions.acquisition_id'],
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'reconstruction_alignments',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('reconstruction_alignment_id', sa.String(length=128), nullable=False),
        sa.Column('alignment_software', sa.String(), nullable=True),
        sa.Column('alignment_method', sa.String(), nullable=True),
        sa.Column('alignment_files', sa.JSON(), nullable=False),
        sa.Column('mtime', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint(
            'sample_id', 'acquisition_id', 'reconstruction_alignment_id'
        ),
    )

    op.drop_table('raw_tomograms')
    op.create_table(
        'raw_tomograms',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('tomogram_id', sa.String(length=128), nullable=False),
        sa.Column('reconstruction_alignment_id', sa.String(length=128), nullable=False),
        sa.Column('pipeline', sa.String(), nullable=True),
        sa.Column('software', sa.String(), nullable=True),
        sa.Column('voxel_size', sa.Float(), nullable=True),
        sa.Column('derived_from', sa.String(length=128), nullable=True),
        sa.Column('image_size_x', sa.Integer(), nullable=True),
        sa.Column('image_size_y', sa.Integer(), nullable=True),
        sa.Column('image_size_z', sa.Integer(), nullable=True),
        sa.Column('mrc_path', sa.String(), nullable=True),
        sa.Column('zarr_path', sa.String(), nullable=True),
        sa.Column('zarr_axes', sa.String(), nullable=True),
        sa.Column('zarr_scale', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint(
            'sample_id',
            'acquisition_id',
            'reconstruction_alignment_id',
            'tomogram_id',
        ),
    )

    op.drop_table('post_processed_tomograms')
    op.create_table(
        'post_processed_tomograms',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('tomogram_id', sa.String(length=128), nullable=False),
        sa.Column('reconstruction_alignment_id', sa.String(length=128), nullable=False),
        sa.Column('denoising_software', sa.String(), nullable=True),
        sa.Column('ctf_software', sa.String(), nullable=True),
        sa.Column('missing_wedge_software', sa.String(), nullable=True),
        sa.Column('voxel_size', sa.Float(), nullable=True),
        sa.Column('derived_from', sa.JSON(), nullable=False),
        sa.Column('image_size_x', sa.Integer(), nullable=True),
        sa.Column('image_size_y', sa.Integer(), nullable=True),
        sa.Column('image_size_z', sa.Integer(), nullable=True),
        sa.Column('mrc_path', sa.String(), nullable=True),
        sa.Column('zarr_path', sa.String(), nullable=True),
        sa.Column('zarr_axes', sa.String(), nullable=True),
        sa.Column('zarr_scale', sa.JSON(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint(
            'sample_id',
            'acquisition_id',
            'reconstruction_alignment_id',
            'tomogram_id',
        ),
    )

    op.drop_table('annotations')
    op.create_table(
        'annotations',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('annotation_id', sa.String(length=128), nullable=False),
        sa.Column('reconstruction_alignment_id', sa.String(length=128), nullable=False),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint(
            'sample_id',
            'acquisition_id',
            'reconstruction_alignment_id',
            'annotation_id',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('annotations')
    op.create_table(
        'annotations',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('annotation_id', sa.String(length=128), nullable=False),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('target_tomogram', sa.String(length=128), nullable=True),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint('sample_id', 'acquisition_id', 'annotation_id'),
    )

    op.drop_table('post_processed_tomograms')
    op.create_table(
        'post_processed_tomograms',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('tomogram_id', sa.String(length=128), nullable=False),
        sa.Column('tilt_series_id', sa.String(length=128), nullable=True),
        sa.Column('denoising_software', sa.String(), nullable=True),
        sa.Column('ctf_software', sa.String(), nullable=True),
        sa.Column('missing_wedge_software', sa.String(), nullable=True),
        sa.Column('voxel_size', sa.Float(), nullable=True),
        sa.Column('derived_from', sa.JSON(), nullable=False),
        sa.Column('image_size_x', sa.Integer(), nullable=True),
        sa.Column('image_size_y', sa.Integer(), nullable=True),
        sa.Column('image_size_z', sa.Integer(), nullable=True),
        sa.Column('mrc_path', sa.String(), nullable=True),
        sa.Column('zarr_path', sa.String(), nullable=True),
        sa.Column('zarr_axes', sa.String(), nullable=True),
        sa.Column('zarr_scale', sa.JSON(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint('sample_id', 'acquisition_id', 'tomogram_id'),
    )

    op.drop_table('raw_tomograms')
    op.create_table(
        'raw_tomograms',
        sa.Column('sample_id', sa.String(length=128), nullable=False),
        sa.Column('acquisition_id', sa.String(length=128), nullable=False),
        sa.Column('tomogram_id', sa.String(length=128), nullable=False),
        sa.Column('tilt_series_id', sa.String(length=128), nullable=True),
        sa.Column('pipeline', sa.String(), nullable=True),
        sa.Column('software', sa.String(), nullable=True),
        sa.Column('voxel_size', sa.Float(), nullable=True),
        sa.Column('derived_from', sa.JSON(), nullable=False),
        sa.Column('image_size_x', sa.Integer(), nullable=True),
        sa.Column('image_size_y', sa.Integer(), nullable=True),
        sa.Column('image_size_z', sa.Integer(), nullable=True),
        sa.Column('mrc_path', sa.String(), nullable=True),
        sa.Column('zarr_path', sa.String(), nullable=True),
        sa.Column('zarr_axes', sa.String(), nullable=True),
        sa.Column('zarr_scale', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(*_ACQ_FK),
        sa.PrimaryKeyConstraint('sample_id', 'acquisition_id', 'tomogram_id'),
    )

    op.drop_table('reconstruction_alignments')
