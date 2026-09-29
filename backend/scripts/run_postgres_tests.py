"""Create and destroy only a uniquely named, isolated PostgreSQL test database."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main():
    admin_url = os.environ["TEST_POSTGRES_ADMIN_URL"]
    parsed = make_url(admin_url)
    name = "alem_test_" + uuid4().hex
    url = parsed.set(database=name).render_as_string(hide_password=False)
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    env = dict(
        os.environ,
        DATABASE_URL=url,
        TEST_DATABASE_URL=url,
        APP_ENV="test",
        COOKIE_SECURE="false",
        STORAGE_DIR=str(Path.cwd() / ".test-storage"),
        AI_MODE="http",
        AI_EXPECTED_MODE="mock",
        AI_BASE_URL="http://127.0.0.1:8000",
        FRONTEND_ORIGIN="http://localhost:5173",
    )
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                env=env,
                check=True,
            )
            subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "tests", *sys.argv[1:]],
                env=env,
                check=True,
            )
        finally:
            # name is generated above, never read from an operator's database URL.
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


if __name__ == "__main__":
    main()
