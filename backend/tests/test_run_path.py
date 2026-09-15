import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from app.features.ingestion.seed import normalize_catalog, replace_snapshot


def seed_cli(tmp_path, catalogue, azure_export=None):
    catalog_file = tmp_path / "catalogue.json"
    catalog_file.write_text(json.dumps(catalogue))
    command = [sys.executable, "-m", "app.seed", "--catalog-file", str(catalog_file)]
    if azure_export:
        azure_file = tmp_path / "azure.json"
        azure_file.write_text(json.dumps(azure_export))
        command += ["--azure-file", str(azure_file)]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("AZURE_SUBSCRIPTION_ID", "AZURE_REGIONS")
    }
    return subprocess.run(command, capture_output=True, text=True, env=environment)


def test_empty_database_is_explicit(postgres_client):
    assert postgres_client.get("/api/status").json()["seeded_at"] is None
    assert postgres_client.get("/api/models").json()["items"] == []
    assert postgres_client.get("/api/health/ready").status_code == 200


def test_repository_examples_use_the_real_seed_path(postgres_client, tmp_path):
    examples = Path(__file__).resolve().parents[2] / "examples"
    catalogue = json.loads((examples / "catalogue.json").read_text())
    azure = json.loads((examples / "azure-models.json").read_text())
    seeded = seed_cli(tmp_path, catalogue, azure)
    assert seeded.returncode == 0, seeded.stderr
    state = postgres_client.get("/api/catalogue/status").json()
    assert state["model_count"] == 2
    assert state["offering_count"] == 3
    assert state["sources"]["azure"]["count"] == 1
    assert all(
        "synthetic" in model["name"]
        for model in postgres_client.get("/api/catalogue/models").json()["items"]
    )


def test_cli_to_postgres_to_http(postgres_client, tmp_path, catalogue, azure_export):
    seeded = seed_cli(tmp_path, catalogue, azure_export)
    assert seeded.returncode == 0, seeded.stderr
    state = postgres_client.get("/api/status").json()
    assert state["model_count"] == 3
    assert state["sources"]["azure"]["status"] == "file"
    page = postgres_client.get("/api/models", params={"provider": "azure", "q": "example"}).json()
    assert page["total"] == 1
    assert page["items"][0]["input_price"] == 0
    detail = postgres_client.get(f"/api/models/{page['items'][0]['id']}").json()
    assert detail["metadata"]["benchmarks"][0]["score"] == 12
    assert detail["azure"][0]["location"] == "eastus"
    assert len(postgres_client.get("/api/providers").json()) == 2
    repeated = seed_cli(tmp_path, catalogue, azure_export)
    assert repeated.returncode == 0, repeated.stderr
    assert postgres_client.get("/api/models").json()["total"] == 3
    assert postgres_client.get(f"/api/models/{page['items'][0]['id']}").status_code == 200


def test_filters_pagination_and_validation(postgres_client, tmp_path, catalogue):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    assert postgres_client.get("/api/models", params={"reasoning": False}).json()["total"] == 1
    assert postgres_client.get("/api/models", params={"q": "%"}).json()["total"] == 0
    assert postgres_client.get("/api/models", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    first = postgres_client.get("/api/models?limit=1").json()
    second = postgres_client.get("/api/models?limit=1&offset=1").json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert postgres_client.get("/api/models?sort=not_a_column").status_code == 422
    assert postgres_client.get("/api/models?limit=101").status_code == 422
    assert postgres_client.get("/api/models?offset=-1").status_code == 422
    assert (
        postgres_client.get("/api/models/00000000-0000-0000-0000-000000000000").status_code == 404
    )


def test_failed_cli_preserves_snapshot(postgres_client, tmp_path, catalogue):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    before = postgres_client.get("/api/status").json()
    catalogue["providers"] = {}
    assert seed_cli(tmp_path, catalogue).returncode != 0
    assert postgres_client.get("/api/status").json() == before
    assert postgres_client.get("/api/models").json()["total"] == 3


def test_transaction_failure_rolls_back_deletes(postgres_client, tmp_path, catalogue):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    providers, models = normalize_catalog(catalogue)
    with psycopg.connect() as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            replace_snapshot(connection, providers + [providers[0]], models, [], {})
    assert postgres_client.get("/api/models").json()["total"] == 3
