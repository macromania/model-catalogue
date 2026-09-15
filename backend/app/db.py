from contextlib import contextmanager
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql").read_text()


class ModelIndexNotReady(RuntimeError):
    pass


def require_model_index(connection):
    state = connection.execute("SELECT catalogue_count FROM seed_state WHERE id=1").fetchone()
    if state is not None and state["catalogue_count"] is None:
        raise ModelIndexNotReady("The model index needs a seed refresh before it can be read.")


def initialize_schema(connection):
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(18420)")
        connection.execute(SCHEMA)
        migrations = (
            (
                "catalogue_models",
                "azure_observations",
                "ALTER TABLE catalogue_models ADD COLUMN azure_observations jsonb NOT NULL DEFAULT '[]'",
            ),
            (
                "models",
                "catalogue_id",
                "ALTER TABLE models ADD COLUMN catalogue_id uuid REFERENCES catalogue_models(id)",
            ),
            (
                "seed_state",
                "catalogue_count",
                "ALTER TABLE seed_state ADD COLUMN catalogue_count integer",
            ),
        )
        for table, column, statement in migrations:
            exists = connection.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() "
                "AND table_name=%s AND column_name=%s",
                [table, column],
            ).fetchone()
            if exists is None:
                connection.execute(statement)
        if (
            connection.execute(
                "SELECT 1 FROM pg_indexes WHERE schemaname=current_schema() AND indexname='models_catalogue_idx'"
            ).fetchone()
            is None
        ):
            connection.execute("CREATE INDEX models_catalogue_idx ON models(catalogue_id)")


@contextmanager
def read_snapshot(pool):
    with pool.connection() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield connection
