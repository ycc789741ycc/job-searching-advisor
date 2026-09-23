"""Gap plans, keyed by Target (domain decision 16, ADR 0005, ADR 0006).

* ``gapplan.plan`` / ``milestone`` / ``task``: owner zone, under RLS. A plan
  holds its Target as a kind plus exactly one reference, and the frozen
  requirements snapshot, so it outlives posting expiry and re-clustering.
* ``assessment.role_fit`` records the requirements a fit was projected from and
  which dimension each mapped to, so a Target's snapshot — and later a résumé's
  requirement coverage — can be read without the role or posting.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database these already exist, with their policies,
by the time this revision runs. The baseline's grants list its schemas by name,
so the grants for ``gapplan`` are made here.
"""

from __future__ import annotations

from alembic import op

revision: str = "0006_gap_plans"
down_revision: str | None = "0005_crawl_source_origin"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLES = ("gapplan.plan", "gapplan.milestone", "gapplan.task")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE assessment.role_fit "
        "ADD COLUMN IF NOT EXISTS requirements jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE assessment.role_fit "
        "ADD COLUMN IF NOT EXISTS requirement_map jsonb NOT NULL DEFAULT '{}'::jsonb"
    )

    op.execute('CREATE SCHEMA IF NOT EXISTS "gapplan"')
    op.execute('GRANT USAGE ON SCHEMA "gapplan" TO app_rw')

    op.execute(
        "CREATE TABLE IF NOT EXISTS gapplan.plan ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " target_kind varchar(16) NOT NULL,"
        " job_posting_id uuid,"
        " subscription_id uuid,"
        " private_posting_id uuid,"
        " target_label varchar(400) NOT NULL,"
        " version integer NOT NULL,"
        " status varchar(16) NOT NULL,"
        " error_code varchar(64),"
        " error_message text,"
        " snapshot jsonb,"
        " gaps jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " projects jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " stepping_stones jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " model_id varchar(128),"
        " template_version varchar(128),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " drafted_at timestamptz,"
        " CONSTRAINT pk_plan PRIMARY KEY (id),"
        " CONSTRAINT ck_plan_one_target CHECK"
        " (num_nonnulls(job_posting_id, subscription_id, private_posting_id) = 1),"
        " CONSTRAINT ck_plan_target_kind CHECK"
        " (target_kind IN ('matchedPosting', 'subscription', 'privatePosting')),"
        " CONSTRAINT ck_plan_status CHECK (status IN ('drafting', 'ready', 'failed'))"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_plan_owner_id ON gapplan.plan (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_plan_owner_created ON gapplan.plan (owner_id, created_at)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS gapplan.milestone ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " plan_id uuid NOT NULL,"
        " position integer NOT NULL,"
        " title varchar(300) NOT NULL,"
        " time_window varchar(64) NOT NULL,"
        " outcome text NOT NULL,"
        " CONSTRAINT pk_milestone PRIMARY KEY (id),"
        " CONSTRAINT fk_milestone_plan_id_plan FOREIGN KEY (plan_id)"
        " REFERENCES gapplan.plan (id) ON DELETE CASCADE"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_milestone_owner_id ON gapplan.milestone (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_milestone_plan_id ON gapplan.milestone (plan_id)")

    op.execute(
        "CREATE TABLE IF NOT EXISTS gapplan.task ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " plan_id uuid NOT NULL,"
        " milestone_id uuid NOT NULL,"
        " position integer NOT NULL,"
        " text text NOT NULL,"
        " due varchar(32) NOT NULL,"
        " closes jsonb NOT NULL,"
        " done_at timestamptz,"
        " CONSTRAINT pk_task PRIMARY KEY (id),"
        " CONSTRAINT fk_task_plan_id_plan FOREIGN KEY (plan_id)"
        " REFERENCES gapplan.plan (id) ON DELETE CASCADE,"
        " CONSTRAINT fk_task_milestone_id_milestone FOREIGN KEY (milestone_id)"
        " REFERENCES gapplan.milestone (id) ON DELETE CASCADE"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_owner_id ON gapplan.task (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_plan_id ON gapplan.task (plan_id)")

    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "gapplan" TO app_rw')
    op.execute(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA "gapplan" '
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw"
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
        op.execute(
            f"CREATE POLICY owner_isolation ON {table} FOR ALL "
            f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
            f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute('DROP SCHEMA IF EXISTS "gapplan"')
    op.execute("ALTER TABLE assessment.role_fit DROP COLUMN IF EXISTS requirement_map")
    op.execute("ALTER TABLE assessment.role_fit DROP COLUMN IF EXISTS requirements")
