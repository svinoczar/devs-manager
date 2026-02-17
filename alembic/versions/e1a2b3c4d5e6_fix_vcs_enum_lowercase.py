"""fix vcs_enum to lowercase values

Revision ID: e1a2b3c4d5e6
Revises: d500d7d5d52d
Create Date: 2026-02-17

"""
from alembic import op

revision = 'e1a2b3c4d5e6'
down_revision = 'd500d7d5d52d'
branch_labels = None
depends_on = None


COLUMNS = [
    ("organizations", "main_vcs"),
    ("contributors",  "vcs_provider"),
    ("projects",      "vcs"),
    ("repositories",  "vcs_provider"),
    ("teams",         "vcs"),
]


def upgrade():
    op.execute("ALTER TYPE vcs_enum RENAME TO vcs_enum_old")
    op.execute("CREATE TYPE vcs_enum AS ENUM ('github', 'gitlab', 'bitbucket', 'svn')")

    for table, column in COLUMNS:
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE vcs_enum
            USING lower({column}::text)::vcs_enum
        """)

    op.execute("DROP TYPE vcs_enum_old")


def downgrade():
    op.execute("ALTER TYPE vcs_enum RENAME TO vcs_enum_old")
    op.execute("CREATE TYPE vcs_enum AS ENUM ('GITHUB', 'GITLAB', 'BITBUCKET', 'SVN')")

    for table, column in COLUMNS:
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE vcs_enum
            USING upper({column}::text)::vcs_enum
        """)

    op.execute("DROP TYPE vcs_enum_old")
