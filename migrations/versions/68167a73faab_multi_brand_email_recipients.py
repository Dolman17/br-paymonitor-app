"""multi-brand email recipients

Revision ID: 68167a73faab
Revises: 79d6f8a29feb
Create Date: 2026-02-26

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "68167a73faab"
down_revision = "79d6f8a29feb"
branch_labels = None
depends_on = None


def upgrade():
    # Convert email_recipients from per-brand rows to per-email rows
    # with per-brand flags.
    with op.batch_alter_table("email_recipients", schema=None) as batch_op:
        # New columns with proper Postgres-friendly boolean defaults
        batch_op.add_column(
            sa.Column(
                "include_blue_ribbon",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "include_forevermore",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

        # Drop old brand_id – FK is handled implicitly by batch_alter_table
        batch_op.drop_column("brand_id")

        # Add index on email for uniqueness/lookups
        batch_op.create_index(
            "ix_email_recipients_email",
            ["email"],
            unique=True,
        )

    # Optional: clear server_default so future migrations stay clean
    with op.batch_alter_table("email_recipients", schema=None) as batch_op:
        batch_op.alter_column(
            "include_blue_ribbon",
            server_default=None,
        )
        batch_op.alter_column(
            "include_forevermore",
            server_default=None,
        )
        batch_op.alter_column(
            "created_at",
            server_default=None,
        )


def downgrade():
    # Best-effort downgrade; you’re unlikely to use this in practice.
    with op.batch_alter_table("email_recipients", schema=None) as batch_op:
        # Drop the email index
        batch_op.drop_index("ix_email_recipients_email")

        # Recreate brand_id (nullable) and FK back to brands.id
        batch_op.add_column(
            sa.Column("brand_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_email_recipients_brand_id_brands",
            "brands",
            ["brand_id"],
            ["id"],
        )

        # Drop the new columns
        batch_op.drop_column("created_at")
        batch_op.drop_column("include_forevermore")
        batch_op.drop_column("include_blue_ribbon")