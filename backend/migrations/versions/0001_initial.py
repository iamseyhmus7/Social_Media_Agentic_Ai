"""Initial pilot schema. Subsequent changes must use explicit Alembic revisions."""
from alembic import op
from backend.app.db import Base

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError('Pilot downgrade deliberately requires a reviewed data backup and explicit migration.')
