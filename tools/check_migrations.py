"""Verify upgrade/check/downgrade/upgrade in a disposable database or PostgreSQL schema."""

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings


def main():
    original = os.environ.get("DATABASE_URL")
    postgres = os.environ.get("TEST_DATABASE_URL")
    schema = "migration_check_" + uuid4().hex
    admin = create_engine(postgres) if postgres else None
    with tempfile.TemporaryDirectory(prefix="keitaro-migrations-") as directory:
        try:
            if admin:
                with admin.begin() as connection:
                    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                url = make_url(postgres).update_query_dict({"options": f"-csearch_path={schema}"})
                os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
            else:
                os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'migrations.db'}"
            get_settings.cache_clear()
            config = Config("alembic.ini")
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, "base")
            command.upgrade(config, "head")
            command.check(config)
            print("Migration round trip passed: " + ("PostgreSQL" if postgres else "SQLite"))
        finally:
            get_settings.cache_clear()
            if original is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original
            if admin:
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                admin.dispose()


if __name__ == "__main__":
    main()
