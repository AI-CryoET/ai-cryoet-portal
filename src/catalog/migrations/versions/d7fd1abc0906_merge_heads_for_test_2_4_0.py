"""merge heads for test-2.4.0

Revision ID: d7fd1abc0906
Revises: 02915ef0dfac, 69798d00c0ef
Create Date: 2026-08-18 16:44:01.569527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7fd1abc0906'
down_revision: Union[str, Sequence[str], None] = ('02915ef0dfac', '69798d00c0ef')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
