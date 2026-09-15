"""per-account CSV import profile for statement layouts

Brazilian credit-card exports (e.g. Sicredi) ship a summary block above
the real transaction table. Storing header_row, delimiter, column map and
amount_semantics on the account means each re-import of that card applies
the same layout without remapping.

Revision ID: 090
Revises: 089
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("import_profile", _JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "import_profile")
