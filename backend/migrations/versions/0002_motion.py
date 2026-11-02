"""Versioned production runs and durable remote jobs."""
from alembic import op
import sqlalchemy as sa
from backend.app.db import RemoteJob

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'pipeline_version' not in {c['name'] for c in sa.inspect(bind).get_columns('runs')}:
        op.add_column('runs', sa.Column('pipeline_version', sa.Integer(), nullable=False, server_default='1'))
    RemoteJob.__table__.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError('Üretim geçmişi korunmalı; geri dönüş açık bir veri taşıması gerektirir.')
