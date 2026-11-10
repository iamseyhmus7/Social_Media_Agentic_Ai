"""Project references and account-wide conservative image budget."""
from alembic import op
from backend.app.db import VisualReference, CloudflareBudget

revision = '0004_visual_quality'
down_revision = '0003_agentic'
branch_labels = depends_on = None


def upgrade():
    for table in (VisualReference.__table__, CloudflareBudget.__table__):
        table.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('Referanslar ve kullanım kayıtları korunmalı.')
