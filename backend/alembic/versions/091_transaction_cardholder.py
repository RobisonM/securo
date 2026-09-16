"""cardholder on transactions for multi-card statement imports

Sicredi (and similar) CSVs expose a Nome / titular column. Persist it so
import review and the transactions grid can show who spent on which card
without overloading payee or notes.

Revision ID: 091
Revises: 090
"""
from alembic import op
import sqlalchemy as sa

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("cardholder", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "cardholder")
