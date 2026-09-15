import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.main import app


@pytest.fixture
def catalogue():
    return {
        "models": {
            "example/example-one": {
                "name": "Example One",
                "benchmarks": [
                    {"name": "Example test", "score": 12, "source": "https://example.com"}
                ],
            }
        },
        "providers": {
            "azure": {
                "name": "Azure",
                "models": {
                    "example-one": {
                        "name": "Example One",
                        "limit": {"context": 1000, "output": 100},
                        "cost": {"input": 0, "output": 1},
                        "reasoning": False,
                    },
                    "unknown": {"name": "Unknown limits"},
                },
            },
            "example": {
                "name": "Example",
                "models": {"example-one": {"name": "Example One", "reasoning": True}},
            },
        },
    }


@pytest.fixture
def azure_export():
    return {
        "locations": {
            "eastus": {
                "value": [
                    {
                        "model": {
                            "name": "example-one",
                            "version": "1",
                            "lifecycleStatus": "GenerallyAvailable",
                            "skus": [{"name": "GlobalStandard"}],
                        },
                    }
                ]
            },
        },
    }


@pytest.fixture
def postgres_client(monkeypatch):
    if os.getenv("TEST_POSTGRES") != "1":
        pytest.skip("Run make verify for isolated real-PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        monkeypatch.setenv(
            "PGOPTIONS", f"-c search_path={schema} -c statement_timeout=15000 -c lock_timeout=5000"
        )
        try:
            with TestClient(app) as client:
                yield client
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
