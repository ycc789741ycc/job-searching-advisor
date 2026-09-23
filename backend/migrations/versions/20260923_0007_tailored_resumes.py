"""Résumés written for a Target: versions, the revision chat, and exports.

Everything in the ``resume`` schema is owner zone, under RLS. A résumé holds its
Target as a kind plus exactly one reference, like a gap plan, with the frozen
snapshot and its requirement coverage.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database these already exist, with their policies,
by the time this revision runs. The baseline's grants list its schemas by name,
so the grants for ``resume`` are made here.
"""

from __future__ import annotations

from alembic import op

revision: str = "0007_tailored_resumes"
down_revision: str | None = "0006_gap_plans"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLES = ("resume.resume", "resume.version", "resume.revision", "resume.export")


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "resume"')
    op.execute('GRANT USAGE ON SCHEMA "resume" TO app_rw')

    op.execute(
        "CREATE TABLE IF NOT EXISTS resume.resume ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " target_kind varchar(16) NOT NULL,"
        " job_posting_id uuid,"
        " subscription_id uuid,"
        " private_posting_id uuid,"
        " target_label varchar(400) NOT NULL,"
        " snapshot jsonb,"
        " coverage jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " template varchar(16) NOT NULL,"
        " options jsonb NOT NULL,"
        " status varchar(16) NOT NULL,"
        " error_code varchar(64),"
        " error_message text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_resume PRIMARY KEY (id),"
        " CONSTRAINT ck_resume_one_target CHECK"
        " (num_nonnulls(job_posting_id, subscription_id, private_posting_id) = 1),"
        " CONSTRAINT ck_resume_target_kind CHECK"
        " (target_kind IN ('matchedPosting', 'subscription', 'privatePosting')),"
        " CONSTRAINT ck_resume_status CHECK (status IN ('drafting', 'ready', 'failed')),"
        " CONSTRAINT ck_resume_template CHECK (template IN ('warm', 'plain', 'brief'))"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_resume_owner_id ON resume.resume (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resume_owner_updated ON resume.resume (owner_id, updated_at)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS resume.version ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " resume_id uuid NOT NULL,"
        " number integer NOT NULL,"
        " label varchar(200) NOT NULL,"
        " content jsonb NOT NULL,"
        " source varchar(16) NOT NULL,"
        " model_id varchar(128),"
        " template_version varchar(128),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_version PRIMARY KEY (id),"
        " CONSTRAINT ck_version_source CHECK (source IN ('generated', 'manual', 'chat')),"
        " CONSTRAINT fk_version_resume_id_resume FOREIGN KEY (resume_id)"
        " REFERENCES resume.resume (id) ON DELETE CASCADE"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_version_owner_id ON resume.version (owner_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_version_resume_number"
        " ON resume.version (resume_id, number)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS resume.revision ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " resume_id uuid NOT NULL,"
        " request text NOT NULL,"
        " reply text NOT NULL,"
        " proposal jsonb,"
        " applied_version_id uuid,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_revision PRIMARY KEY (id),"
        " CONSTRAINT fk_revision_resume_id_resume FOREIGN KEY (resume_id)"
        " REFERENCES resume.resume (id) ON DELETE CASCADE"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_revision_owner_id ON resume.revision (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_revision_resume_created"
        " ON resume.revision (resume_id, created_at)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS resume.export ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " version_id uuid NOT NULL,"
        " template varchar(16) NOT NULL,"
        " status varchar(16) NOT NULL,"
        " storage_key varchar(512),"
        " error_code varchar(64),"
        " error_message text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " finished_at timestamptz,"
        " CONSTRAINT pk_export PRIMARY KEY (id),"
        " CONSTRAINT ck_export_status CHECK (status IN ('rendering', 'ready', 'failed')),"
        " CONSTRAINT fk_export_version_id_version FOREIGN KEY (version_id)"
        " REFERENCES resume.version (id) ON DELETE CASCADE"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_owner_id ON resume.export (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_version_id ON resume.export (version_id)")

    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "resume" TO app_rw')
    op.execute(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA "resume" '
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
    op.execute('DROP SCHEMA IF EXISTS "resume"')
