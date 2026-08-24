#!/usr/bin/env bash
# Execute a maintenance-window migration only when an operator has selected a
# concrete, reviewed Alembic revision.  `head` is intentionally not a valid
# target: it would make a maintenance invocation depend on unreviewed image
# contents.
set -euo pipefail

target="${MIGRATION_TARGET:-}"
if [[ -z "${target}" || "${target}" == "head" || ! "${target}" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "MIGRATION_TARGET must name a reviewed, non-head Alembic revision" >&2
    exit 2
fi

# Do not let Alembic's symbolic targets or a typo turn this maintenance command
# into a downgrade.  In particular, `alembic upgrade base` emits destructive
# SQL.  The target must be one exact revision shipped in this image and must
# not be behind the database's current revision.
python3 - "${target}" <<'PY'
import asyncio
import os
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def reject(message: str) -> None:
    print(f"MIGRATION_TARGET {message}", file=sys.stderr)
    raise SystemExit(2)


target = sys.argv[1]
script = ScriptDirectory.from_config(Config("alembic.ini"))
known_revisions = {revision.revision for revision in script.walk_revisions()}
if target not in known_revisions:
    reject("must name one concrete Alembic revision shipped in this image")


async def current_revisions() -> tuple[str, ...]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required to validate migration direction", file=sys.stderr)
        raise SystemExit(3)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            try:
                rows = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError as exc:
                # A database with no Alembic table is a legitimate first
                # deployment.  Other connection/query failures must fail
                # closed instead of blindly running a migration.
                await connection.rollback()
                sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
                missing_sqlite_table = "no such table: alembic_version" in str(
                    getattr(exc, "orig", exc)
                ).lower()
                if sqlstate != "42P01" and not missing_sqlite_table:
                    print("cannot inspect current Alembic revision", file=sys.stderr)
                    raise SystemExit(3)
                return ()
            return tuple(str(value) for value in rows.scalars().all())
    finally:
        await engine.dispose()


current = asyncio.run(current_revisions())
for revision in current:
    if revision not in known_revisions:
        print("current Alembic revision is not shipped in this image", file=sys.stderr)
        raise SystemExit(3)
    try:
        list(script.iterate_revisions(target, revision))
    except RangeNotAncestorError:
        reject("must not be an ancestor of the current Alembic revision")
PY

exec python3 -m alembic upgrade "${target}"
