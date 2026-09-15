import copy
import subprocess
from argparse import Namespace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

import app.main as application
from app.db import initialize_schema
from app.features.ingestion import cloud, seed
from tests.test_run_path import seed_cli


@pytest.fixture
def cloud_args():
    return Namespace(
        azure_subscription="00000000-0000-0000-0000-000000000001",
        azure_regions="eastus",
        managed_identity_client_id="00000000-0000-0000-0000-000000000002",
        azure_file=None,
        catalog_file=None,
    )


def test_cloud_rejects_incomplete_configuration_before_connecting(cloud_args, monkeypatch):
    cloud_args.managed_identity_client_id = None
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda **kwargs: pytest.fail("Database must not be contacted for incomplete configuration"),
    )
    with pytest.raises(ValueError, match="managed identity"):
        cloud.run(cloud_args, "fixture-password")


def test_managed_identity_is_explicit_and_does_not_use_az_cli(monkeypatch):
    calls = []

    class Credential:
        def __init__(self, client_id):
            calls.append(client_id)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_token(self, scope):
            calls.append(scope)
            return SimpleNamespace(token="fixture-identity-token")

    monkeypatch.setattr(seed, "ManagedIdentityCredential", Credential)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("Azure CLI must not be used")
    )

    def response(request):
        assert request.headers["Authorization"] == "Bearer fixture-identity-token"
        return httpx.Response(200, json={"value": []})

    identity = "00000000-0000-0000-0000-000000000002"
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        seed.fetch_azure(client, "00000000-0000-0000-0000-000000000001", ["eastus"], identity)
    assert calls == [identity, "https://management.azure.com/.default"]


def test_cloud_grant_failure_rolls_back_snapshot(
    postgres_client, tmp_path, catalogue, cloud_args, monkeypatch
):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    before = postgres_client.get("/api/status").json()
    changed = copy.deepcopy(catalogue)
    changed["providers"]["azure"]["models"]["extra"] = {"name": "New cloud model"}
    providers, models = seed.normalize_catalog(changed)
    monkeypatch.setattr(cloud, "load_snapshot", lambda args: (providers, models, [], {}))

    def fail_grant(connection, password):
        assert connection.execute("SELECT count(*) FROM models").fetchone()[0] == 4
        raise RuntimeError("Injected reader grant failure")

    monkeypatch.setattr(cloud, "grant_reader", fail_grant)
    with pytest.raises(RuntimeError, match="grant failure"):
        cloud.run(cloud_args, "fixture-password")
    assert postgres_client.get("/api/status").json() == before
    assert postgres_client.get("/api/models").json()["total"] == 3


def test_competing_cloud_seed_fails_before_fetch(postgres_client, cloud_args, monkeypatch):
    monkeypatch.setattr(
        cloud, "load_snapshot", lambda args: pytest.fail("A competing job must not fetch")
    )
    with psycopg.connect(autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", [cloud.JOB_LOCK])
        try:
            with pytest.raises(RuntimeError, match="already running"):
                cloud.run(cloud_args, "fixture-password")
        finally:
            holder.execute("SELECT pg_advisory_unlock(%s)", [cloud.JOB_LOCK])


def test_cloud_api_startup_does_not_run_ddl(postgres_client, monkeypatch):
    monkeypatch.setenv("CATALOGUE_INIT_SCHEMA", "false")
    monkeypatch.setattr(
        application, "initialize_schema", lambda connection: pytest.fail("DDL must be disabled")
    )
    with TestClient(application.app) as client:
        assert client.get("/api/health/ready").status_code == 200
        assert client.get("/api/models").json()["items"] == []


def test_non_superuser_can_create_and_refresh_a_read_only_role(
    postgres_client, monkeypatch, catalogue
):
    suffix = uuid4().hex
    owner, reader, schema = f"owner_{suffix}", f"reader_{suffix}", f"schema_{suffix}"
    monkeypatch.setattr(cloud, "READER_ROLE", reader)
    with psycopg.connect(autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} CREATEROLE").format(sql.Identifier(owner)))
        admin.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(schema), sql.Identifier(owner)
            )
        )
        try:
            with psycopg.connect() as connection:
                connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
                connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                initialize_schema(connection)
                providers, offerings = seed.normalize_catalog(catalogue)
                seed.replace_snapshot(connection, providers, offerings, [], {}, catalogue["models"])
                connection.execute(
                    sql.SQL("GRANT CREATE ON SCHEMA {} TO PUBLIC").format(sql.Identifier(schema))
                )
                cloud.grant_reader(connection, "Fixture-only-password-A1!")
                cloud.grant_reader(connection, "Fixture-only-password-A1!")
                assert not connection.execute(
                    "SELECT has_schema_privilege(%s, %s, 'CREATE')", [reader, schema]
                ).fetchone()[0]
            monkeypatch.setenv("PGUSER", reader)
            monkeypatch.setenv("PGPASSWORD", "Fixture-only-password-A1!")
            monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
            monkeypatch.setenv("CATALOGUE_INIT_SCHEMA", "false")
            with TestClient(application.app) as client:
                page = client.get("/api/catalogue/models")
                assert page.status_code == 200
                assert page.json()["total"] == 2
                model_id = page.json()["items"][0]["id"]
                assert client.get(f"/api/catalogue/models/{model_id}").status_code == 200
            with psycopg.connect() as reader_connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    reader_connection.execute("DELETE FROM catalogue_models")
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            for role in (reader, owner):
                if admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [role]).fetchone():
                    admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
