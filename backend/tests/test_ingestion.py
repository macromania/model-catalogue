import copy
import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from app.features.ingestion.seed import fetch_azure, normalize_azure, normalize_catalog


def test_normalization_preserves_unknown_zero_and_false(catalogue):
    providers, models = normalize_catalog(catalogue)
    assert len(providers) == 2
    assert len(models) == 3
    first, unknown, _ = models
    assert first[8] == 0
    assert first[10] is False
    assert unknown[6] is None
    assert unknown[10] is None
    assert first[4] == "example/example-one"
    assert [row[:13] for row in models] == [row[:13] for row in normalize_catalog(catalogue)[1]]


def test_ambiguous_metadata_is_not_guessed(catalogue):
    catalogue["models"]["another/example-one"] = {"name": "Different model"}
    _, models = normalize_catalog(catalogue)
    assert models[0][4] is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "free", True])
def test_invalid_price_rejected(catalogue, value):
    catalogue["providers"]["azure"]["models"]["example-one"]["cost"]["input"] = value
    with pytest.raises(ValueError):
        normalize_catalog(catalogue)


def test_empty_snapshot_rejected():
    with pytest.raises(ValueError, match="empty"):
        normalize_catalog({"providers": {}, "models": {}})


def test_azure_duplicate_skus_preserved(azure_export):
    extra = copy.deepcopy(azure_export["locations"]["eastus"]["value"][0])
    extra["skuName"] = "S1"
    azure_export["locations"]["eastus"]["value"].append(extra)
    rows = normalize_azure(azure_export)
    assert len(rows) == 1
    assert len(rows[0][3].obj["entries"]) == 2


def test_incomplete_file_export_rejected(azure_export):
    azure_export["locations"]["eastus"]["nextLink"] = "https://management.azure.com/next"
    with pytest.raises(ValueError, match="incomplete"):
        normalize_azure(azure_export)


def test_live_azure_pagination_and_token_scope(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({"accessToken": "test-token"})),
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [{"model": {"name": "one", "version": "1"}}],
                    "nextLink": "https://management.azure.com/next",
                },
            )
        return httpx.Response(200, json={"value": [{"model": {"name": "two", "version": "1"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_azure(client, "00000000-0000-0000-0000-000000000001", ["eastus"])
    assert len(normalize_azure(result)) == 2
    assert len(requests) == 2


@pytest.mark.parametrize("link", ["http://management.azure.com/next", "https://example.com/next"])
def test_azure_rejects_off_origin_pagination(monkeypatch, link):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({"accessToken": "test-token"})),
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": [], "nextLink": link}),
        )
    ) as client:
        with pytest.raises(ValueError, match="outside"):
            fetch_azure(client, "00000000-0000-0000-0000-000000000001", ["eastus"])


def test_all_regions_discovers_physical_regions_and_preserves_empty_results(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({"accessToken": "test-token"})),
    )
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path.endswith("/locations"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "name": "eastus",
                            "displayName": "East US",
                            "type": "Region",
                            "metadata": {"regionType": "Physical"},
                        },
                        {
                            "name": "westus",
                            "displayName": "West US",
                            "type": "Region",
                            "metadata": {"regionType": "Physical"},
                        },
                        {
                            "name": "northcentralus",
                            "type": "Region",
                            "metadata": {"regionType": "Physical"},
                        },
                        {"name": "europe", "type": "Region", "metadata": {"regionType": "Logical"}},
                    ]
                },
            )
        if request.url.path.endswith("/providers/Microsoft.CognitiveServices"):
            return httpx.Response(
                200,
                json={
                    "resourceTypes": [
                        {
                            "resourceType": "locations/models",
                            "apiVersions": ["2024-10-01"],
                            "locations": ["East US", "West US", "Global"],
                        }
                    ]
                },
            )
        if "/eastus/" in request.url.path:
            return httpx.Response(200, json={"value": [{"model": {"name": "one", "version": "1"}}]})
        return httpx.Response(200, json={"value": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_azure(client, "00000000-0000-0000-0000-000000000001", ["all"])
    assert list(result["locations"]) == ["eastus", "westus"]
    assert result["empty_locations"] == ["westus"]
    assert result["unsupported_locations"] == ["northcentralus"]
    assert result["non_physical_locations"] == ["global"]
    assert result["region_scope"] == "all_supported_physical_regions"
    assert len(requested) == 4


def test_authorization_propagation_retry_is_bounded(monkeypatch):
    from app.features.ingestion.seed import azure_items

    attempts = []
    sleeps = []
    monkeypatch.setattr("app.features.ingestion.seed.time.sleep", sleeps.append)

    def handler(request):
        attempts.append(request)
        return httpx.Response(403, json={"error": {"code": "AuthorizationFailed"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            azure_items(client, "https://management.azure.com/example", "fixture", 2)
    assert len(attempts) == 3
    assert sleeps == [2, 4]


def test_all_cannot_be_mixed_with_explicit_regions():
    with httpx.Client() as client:
        with pytest.raises(ValueError, match="by itself"):
            fetch_azure(client, "00000000-0000-0000-0000-000000000001", ["all", "eastus"])
