"""Sign in with Google: the table that links an outside identity to an account.

`identity.federated_identity` sits beside `identity.password_credential`, and
it needs the same row-level-security exception: the Google callback has to
find the account an identity belongs to before there is an `app.user_id`. The
policy therefore allows access when the setting is unset, which only the
authentication path does, and restricts to the owner whenever it is set, which
covers every request handler (ADR 0008).

The baseline builds tables from the live ORM metadata, so on a fresh database
this table already exists with the ordinary owner-only policy. Every statement
is guarded, and the policy is replaced rather than added, as in 0002.
"""

from __future__ import annotations

from alembic import op

revision: str = "0008_federated_identity"
down_revision: str | None = "0007_tailored_resumes"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLE = "identity.federated_identity"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS identity.federated_identity (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            account_id uuid NOT NULL
                REFERENCES identity.account (id) ON DELETE CASCADE,
            provider varchar(16) NOT NULL,
            subject varchar(255) NOT NULL,
            email_at_link varchar(320) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_federated_identity_provider_subject UNIQUE (provider, subject),
            CONSTRAINT uq_federated_identity_owner_provider UNIQUE (owner_id, provider)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_federated_identity_owner_id "
        "ON identity.federated_identity (owner_id)"
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO app_rw")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_TABLE}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_TABLE} FOR ALL "
        f"USING (coalesce(current_setting('{_APP_USER}', true), '') = '' "
        f"       OR owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (coalesce(current_setting('{_APP_USER}', true), '') = '' "
        f"            OR owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
