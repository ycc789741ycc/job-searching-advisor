"""Subscriptions are to a role at a company, with an optional link (domain decision 19).

``market_user.company_subscription`` keeps its name — the fan-out RLS policy is
keyed on it — and gains the role and the link. A user can now watch several
roles at one company, so uniqueness moves from (owner, company) to
(owner, company, role title). Rows from before this have no role and keep an
empty title, which still satisfies the new constraint.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database these columns already exist.
"""

from __future__ import annotations

from alembic import op

revision: str = "0004_role_subscriptions"
down_revision: str | None = "0003_role_map_setting"
branch_labels = None
depends_on = None

_TABLE = "market_user.company_subscription"
_UNIQUE = "uq_company_subscription_owner_id"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS role_title varchar(255) NOT NULL DEFAULT ''"
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS role_id uuid")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS url varchar(1024)")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_UNIQUE}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE} UNIQUE (owner_id, company_id, role_title)"
    )


def downgrade() -> None:
    # Keeps one row per (owner, company) so the old constraint can come back;
    # the extra roles a user watched at the same company are lost.
    # The table name is this module's constant, never input.
    duplicates = f"DELETE FROM {_TABLE} a USING {_TABLE} b "  # noqa: S608
    op.execute(
        duplicates + "WHERE a.owner_id = b.owner_id AND a.company_id = b.company_id AND a.id > b.id"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_UNIQUE}")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE} UNIQUE (owner_id, company_id)")
    for column in ("url", "role_id", "role_title"):
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {column}")
