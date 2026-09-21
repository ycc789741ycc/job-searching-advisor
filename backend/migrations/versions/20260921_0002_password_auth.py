"""Own email and password sign-in, replacing the hosted provider.

Adds the two tables the identity module needs and relaxes `account` so an
address is the thing someone signs in with.

Row-level security here needs the same exception `identity.account` already
has: authentication runs *before* there is an `app.user_id` to compare
against, by definition. The policies therefore allow access when the setting
is unset — which only the authentication path does — and restrict to the owner
whenever it is set, which is every request handler.
"""

from __future__ import annotations

from alembic import op

revision: str = "0002_password_auth"
down_revision: str | None = "0001_baseline"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_NEW_TABLES = ("password_credential", "refresh_token")


def upgrade() -> None:
    # --- account: the email is now the sign-in identifier ------------------
    # Existing rows came from the hosted provider and may have no address.
    # They are given an unusable one rather than being deleted, so the
    # constraint can be added without losing anything.
    op.execute(
        "UPDATE identity.account SET email = 'migrated+' || id::text || '@invalid' "
        "WHERE email IS NULL"
    )
    op.execute("ALTER TABLE identity.account ALTER COLUMN email SET NOT NULL")
    op.execute("ALTER TABLE identity.account ADD CONSTRAINT uq_account_email UNIQUE (email)")
    # Null for an account that only has a password; reserved for a later
    # external identity such as Google.
    op.execute("ALTER TABLE identity.account ALTER COLUMN auth_subject DROP NOT NULL")

    # --- password_credential ------------------------------------------------
    op.execute(
        """
        CREATE TABLE identity.password_credential (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            account_id uuid NOT NULL
                REFERENCES identity.account (id) ON DELETE CASCADE,
            password_hash text NOT NULL,
            failed_attempts integer NOT NULL DEFAULT 0,
            last_failed_at timestamptz,
            password_updated_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_password_credential_owner_id UNIQUE (owner_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_password_credential_owner_id ON identity.password_credential (owner_id)"
    )

    # --- refresh_token ------------------------------------------------------
    # The token is stored as a SHA-256 digest: a database leak must not hand
    # over live sessions.
    op.execute(
        """
        CREATE TABLE identity.refresh_token (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            account_id uuid NOT NULL
                REFERENCES identity.account (id) ON DELETE CASCADE,
            token_hash varchar(64) NOT NULL,
            family_id uuid NOT NULL,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_refresh_token_token_hash UNIQUE (token_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_refresh_token_owner_family ON identity.refresh_token (owner_id, family_id)"
    )
    op.execute("CREATE INDEX ix_refresh_token_owner_id ON identity.refresh_token (owner_id)")

    # --- grants and row-level security -------------------------------------
    for table in _NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON identity.{table} TO app_rw")
        op.execute(f"ALTER TABLE identity.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE identity.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON identity.{table} FOR ALL "
            f"USING (coalesce(current_setting('{_APP_USER}', true), '') = '' "
            "        OR owner_id::text = current_setting('app.user_id', true)) "
            f"WITH CHECK (coalesce(current_setting('{_APP_USER}', true), '') = '' "
            "            OR owner_id::text = current_setting('app.user_id', true))"
        )


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS owner_isolation ON identity.{table}")
        op.execute(f"DROP TABLE IF EXISTS identity.{table}")
    op.execute("ALTER TABLE identity.account DROP CONSTRAINT IF EXISTS uq_account_email")
    op.execute("ALTER TABLE identity.account ALTER COLUMN email DROP NOT NULL")
