import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql

from app.db import initialize_schema
from app.features.ingestion.seed import normalize_catalog, replace_snapshot
from app.main import app
from tests.test_run_path import seed_cli


def test_both_azure_providers_are_enriched(postgres_client, tmp_path, catalogue, azure_export):
    catalogue["providers"]["azure-cognitive-services"] = copy.deepcopy(
        catalogue["providers"]["azure"]
    )
    result = seed_cli(tmp_path, catalogue, azure_export)
    assert result.returncode == 0, result.stderr
    page = postgres_client.get("/api/models?provider=azure-cognitive-services&q=example").json()
    detail = postgres_client.get(f"/api/models/{page['items'][0]['id']}").json()
    assert detail["azure"][0]["location"] == "eastus"
    assert detail["azure_source"]["status"] == "file"


def test_file_provenance_is_not_rewritten(postgres_client, tmp_path, catalogue, azure_export):
    azure_export["fetched_at"] = "2020-01-01T00:00:00Z"
    azure_export["api_version"] = "2023-05-01"
    result = seed_cli(tmp_path, catalogue, azure_export)
    assert result.returncode == 0, result.stderr
    sources = postgres_client.get("/api/status").json()["sources"]
    assert sources["azure"]["fetched_at"] == "2020-01-01T00:00:00Z"
    assert sources["azure"]["api_version"] == "2023-05-01"
    assert sources["azure"]["imported_at"] != sources["azure"]["fetched_at"]
    assert sources["models_dev"]["fetched_at"] is None


def test_missing_file_provenance_stays_unknown(postgres_client, tmp_path, catalogue, azure_export):
    assert seed_cli(tmp_path, catalogue, azure_export).returncode == 0
    source = postgres_client.get("/api/status").json()["sources"]["azure"]
    assert source["fetched_at"] is None
    assert source["api_version"] is None


def test_large_offset_is_client_error(postgres_client):
    assert postgres_client.get("/api/models?offset=9223372036854775808").status_code == 422


def test_list_keeps_one_snapshot_during_refresh(postgres_client, tmp_path, catalogue, monkeypatch):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    updated = copy.deepcopy(catalogue)
    updated["providers"]["azure"]["models"]["extra"] = {"name": "Extra"}
    providers, models = normalize_catalog(updated)
    original_pool = app.state.pool

    class InterleavedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args):
            cursor = self.connection.execute(statement, *args)
            if statement.startswith("SELECT count(*)"):
                with psycopg.connect() as writer:
                    replace_snapshot(writer, providers, models, [], {})
            return cursor

    class InterleavedPool:
        @contextmanager
        def connection(self):
            with original_pool.connection() as connection:
                yield InterleavedConnection(connection)

    monkeypatch.setattr(app.state, "pool", InterleavedPool())
    response = postgres_client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["total"] == len(response.json()["items"]) == 3
    monkeypatch.setattr(app.state, "pool", original_pool)
    assert postgres_client.get("/api/models").json()["total"] == 4


def test_concurrent_schema_initializers(postgres_client):
    schema = "race_" + uuid4().hex
    barrier = Barrier(2)
    with psycopg.connect(autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

        def initialize():
            with psycopg.connect() as connection:
                connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                barrier.wait(timeout=10)
                initialize_schema(connection)
                return connection.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                    [schema],
                ).fetchone()[0]

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                assert list(executor.map(lambda _: initialize(), range(2))) == [7, 7]
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
