"""Why a source is crawled: the platform's baseline list, or user demand.

``market.crawl_source.origin`` is ``baseline`` or ``demand`` (domain decision
15). It never records who asked. Existing rows all came from subscriptions, so
they are ``demand``. The baseline rows themselves are loaded after migrations
by ``make migrate`` (``cli.seed_baseline``), from a list kept in code.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the column already exists.
"""

from __future__ import annotations

from alembic import op

revision: str = "0005_crawl_source_origin"
down_revision: str | None = "0004_role_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE market.crawl_source "
        "ADD COLUMN IF NOT EXISTS origin varchar(16) NOT NULL DEFAULT 'demand'"
    )
    op.execute("ALTER TABLE market.crawl_source DROP CONSTRAINT IF EXISTS ck_crawl_source_origin")
    op.execute(
        "ALTER TABLE market.crawl_source ADD CONSTRAINT ck_crawl_source_origin "
        "CHECK (origin IN ('baseline', 'demand'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE market.crawl_source DROP CONSTRAINT IF EXISTS ck_crawl_source_origin")
    op.execute("ALTER TABLE market.crawl_source DROP COLUMN IF EXISTS origin")
