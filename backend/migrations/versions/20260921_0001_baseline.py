"""Baseline: schemas, tables, least-privilege grants and row-level security.

Implements docs/technical_boundaries.md section 3. Three things matter here
beyond the tables themselves:

* ``crawler_rw`` gets the shared market zone and the outbox, and **no grant at
  all** on any user schema. A mistake in crawler code fails at the database.
* Every owner-zone table has RLS keyed on the ``app.user_id`` transaction
  setting, so forgetting a ``WHERE owner_id`` returns nothing rather than
  another user's rows.
* ``app_rw`` may read the shared market zone but may not write postings — only
  the crawler does that — except ``crawl_source``, which the worker
  materialises from subscriptions.
"""

from __future__ import annotations

from alembic import op

from app.models import OWNER_ZONE_TABLES, SCHEMAS, SHARED_MARKET_TABLES, metadata

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"


def upgrade() -> None:
    bind = op.get_bind()

    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    metadata.create_all(bind=bind, checkfirst=True)

    # --- grants ------------------------------------------------------------
    for schema in SCHEMAS:
        op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO app_rw')

    # app_rw: full rights on its own module schemas.
    for schema in ("identity", "profile", "market_user", "rolemap", "assessment", "outbox"):
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO app_rw'
        )
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw"
        )

    # app_rw on the shared market zone: read-only, except crawl_source, which
    # the worker materialises from market_user without user ids.
    op.execute('GRANT SELECT ON ALL TABLES IN SCHEMA "market" TO app_rw')
    op.execute("GRANT INSERT, UPDATE, DELETE ON market.crawl_source TO app_rw")
    op.execute("GRANT INSERT ON market.company TO app_rw")

    # crawler_rw: the shared zone and the outbox. Nothing else, ever.
    op.execute('GRANT USAGE ON SCHEMA "market" TO crawler_rw')
    op.execute('GRANT USAGE ON SCHEMA "outbox" TO crawler_rw')
    for table in SHARED_MARKET_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO crawler_rw")
    op.execute("GRANT INSERT ON outbox.event TO crawler_rw")
    op.execute("GRANT SELECT ON outbox.event TO crawler_rw")

    # aggregator: reserved for the interview-report aggregation job, which
    # arrives with InterviewReport in a later phase.
    op.execute('GRANT USAGE ON SCHEMA "market" TO aggregator')

    # --- row-level security ------------------------------------------------
    for qualified in OWNER_ZONE_TABLES:
        schema, _, table = qualified.partition(".")
        op.execute(f'ALTER TABLE "{schema}"."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{schema}"."{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY owner_isolation ON "{schema}"."{table}" '
            "FOR ALL "
            f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
            f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
        )

    # identity.account has no owner_id — it *is* the owner, which makes it the
    # one table RLS cannot be keyed on in the usual way: sign-in has to find or
    # create the row *before* there is an app.user_id to compare against.
    #
    # So the policy is conditional. Inside a `for_user` transaction a caller
    # sees only their own row, which is what protects every request handler.
    # In a session with no app.user_id — used by exactly one method,
    # IdentityService.ensure_account — the bootstrap lookup is allowed through.
    op.execute("ALTER TABLE identity.account ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE identity.account FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY owner_isolation ON identity.account FOR ALL "
        f"USING (coalesce(current_setting('{_APP_USER}', true), '') = '' "
        f"        OR id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (coalesce(current_setting('{_APP_USER}', true), '') = '' "
        f"            OR id::text = current_setting('{_APP_USER}', true))"
    )

    # --- the one deliberate cross-user read --------------------------------
    #
    # When the crawler reports that a company's postings changed, something has
    # to work out which users watch that company. The crawler cannot: it has no
    # grant on any user schema, and that is the point. So the fan-out happens in
    # the worker's outbox dispatcher, which needs to read two columns across all
    # users.
    #
    # Rather than give app_rw BYPASSRLS, these two tables get an extra
    # SELECT-only policy gated on a transaction setting the dispatcher sets and
    # nothing else does. It is narrow, it is greppable, and it cannot be used to
    # read evidence, credentials, assessments or pasted JDs.
    for table in ("company_subscription", "market_preference"):
        op.execute(
            f"CREATE POLICY fanout_read ON market_user.{table} FOR SELECT "
            "USING (current_setting('app.fanout', true) = 'on')"
        )

    # --- indexes that only make sense as raw DDL ---------------------------
    op.execute(
        "CREATE INDEX ix_posting_embedding_vector ON market.posting_embedding "
        "USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS market.ix_posting_embedding_vector")
    for table in ("company_subscription", "market_preference"):
        op.execute(f"DROP POLICY IF EXISTS fanout_read ON market_user.{table}")
    for qualified in (*OWNER_ZONE_TABLES, "identity.account"):
        schema, _, table = qualified.partition(".")
        op.execute(f'DROP POLICY IF EXISTS owner_isolation ON "{schema}"."{table}"')
    metadata.drop_all(bind=bind, checkfirst=True)
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
