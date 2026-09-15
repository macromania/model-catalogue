"""Manual cloud seed job with a single-run guard and transactional reader setup."""

import logging
import os

import httpx
import psycopg
from azure.core.exceptions import AzureError
from psycopg import sql

from app.features.ingestion.seed import load_snapshot, parse_args, replace_snapshot

logger = logging.getLogger(__name__)
READER_ROLE = "catalogue_reader"
JOB_LOCK = 18424


def grant_reader(connection, password: str):
    exists = connection.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        [READER_ROLE],
    ).fetchone()
    if exists and any(exists):
        raise RuntimeError("The existing API role has unexpected privileged attributes")
    operation = "ALTER ROLE" if exists else "CREATE ROLE"
    connection.execute(
        sql.SQL("{} {} LOGIN NOINHERIT PASSWORD {}").format(
            sql.SQL(operation), sql.Identifier(READER_ROLE), sql.Literal(password)
        )
    )
    database = connection.execute("SELECT current_database()").fetchone()[0]
    schema = connection.execute("SELECT current_schema()").fetchone()[0]
    connection.execute(
        sql.SQL("REVOKE CREATE ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema))
    )
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(READER_ROLE)
        )
    )
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(READER_ROLE)
        )
    )
    connection.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(READER_ROLE)
        )
    )
    connection.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
            sql.Identifier(schema), sql.Identifier(READER_ROLE)
        )
    )
    for table_name in (
        "models",
        "catalogue_models",
        "catalogue_model_keys",
        "catalogue_model_redirects",
        "providers",
        "azure_models",
        "seed_state",
    ):
        table = sql.Identifier(schema, table_name).as_string(connection)
        readable, writable, can_create = connection.execute(
            "SELECT has_table_privilege(%s, %s, 'SELECT'), "
            "has_table_privilege(%s, %s, 'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES'), "
            "has_schema_privilege(%s, %s, 'CREATE')",
            [READER_ROLE, table, READER_ROLE, table, READER_ROLE, schema],
        ).fetchone()
        if not readable or writable or can_create:
            raise RuntimeError(f"The API role does not have read-only access to {table_name}")


def run(args, reader_password: str):
    if not all((args.azure_subscription, args.azure_regions, args.managed_identity_client_id)):
        raise ValueError(
            "Cloud seeding requires subscription, regions and a managed identity client ID"
        )
    if args.azure_file or args.catalog_file:
        raise ValueError("Cloud seeding requires live sources, not local file overrides")
    if not reader_password:
        raise ValueError("CATALOGUE_READER_PASSWORD is required")
    with psycopg.connect(autocommit=True) as connection:
        acquired = connection.execute("SELECT pg_try_advisory_lock(%s)", [JOB_LOCK]).fetchone()[0]
        if not acquired:
            raise RuntimeError("Another cloud seed execution is already running")
        try:
            snapshot = load_snapshot(args)
            with connection.transaction():
                replace_snapshot(connection, *snapshot)
                grant_reader(connection, reader_password)
            logger.info(
                "Cloud seed committed: %s provider offerings, %s Azure observations; API role is read-only.",
                len(snapshot[1]),
                len(snapshot[2]),
            )
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", [JOB_LOCK])


def main():
    args = parse_args()
    run(args, os.environ.get("CATALOGUE_READER_PASSWORD", ""))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        main()
    except psycopg.Error as error:
        logger.error(
            "Cloud database operation failed (SQLSTATE %s); no replacement snapshot was committed.",
            error.sqlstate or "unknown",
        )
        raise SystemExit(1) from error
    except (ValueError, RuntimeError, OSError, httpx.HTTPError, AzureError) as error:
        logger.error("Cloud seed failed; no replacement snapshot was committed: %s", error)
        raise SystemExit(1) from error
