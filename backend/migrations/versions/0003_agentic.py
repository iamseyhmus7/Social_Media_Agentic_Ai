"""Autonomous duration and durable feedback requests."""
from alembic import op
import sqlalchemy as sa
from backend.app.db import Feedback

revision = '0003_agentic'
down_revision = '0002'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'duration_auto' not in {c['name'] for c in sa.inspect(bind).get_columns('projects')}:
        op.add_column('projects', sa.Column('duration_auto', sa.Boolean(), nullable=False, server_default=sa.false()))
    Feedback.__table__.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError('Üretim ve geri bildirim geçmişi korunmalı.')
