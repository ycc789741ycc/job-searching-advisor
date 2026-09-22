"""The user's choice of how many roles a role map analyses (ADR 0003).

One owner-zone row per user in ``rolemap.role_map_setting``; no row means the
default. The bound (3-20) is a domain rule, and the CHECK below is the last line
behind it.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database this table and its row-level security
already exist by the time this revision runs.
"""

from __future__ import annotations

from alembic import op

revision: str = "0003_role_map_setting"
down_revision: str | None = "0002_password_auth"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rolemap.role_map_setting (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            role_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_role_map_setting PRIMARY KEY (id),
            CONSTRAINT uq_role_map_setting_owner_id UNIQUE (owner_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_map_setting_owner_id "
        "ON rolemap.role_map_setting (owner_id)"
    )
    op.execute(
        "ALTER TABLE rolemap.role_map_setting "
        "DROP CONSTRAINT IF EXISTS ck_role_map_setting_role_count"
    )
    op.execute(
        "ALTER TABLE rolemap.role_map_setting ADD CONSTRAINT ck_role_map_setting_role_count "
        "CHECK (role_count BETWEEN 3 AND 20)"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rolemap.role_map_setting TO app_rw")
    op.execute("ALTER TABLE rolemap.role_map_setting ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rolemap.role_map_setting FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS owner_isolation ON rolemap.role_map_setting")
    op.execute(
        "CREATE POLICY owner_isolation ON rolemap.role_map_setting FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS owner_isolation ON rolemap.role_map_setting")
    op.execute("DROP TABLE IF EXISTS rolemap.role_map_setting")
