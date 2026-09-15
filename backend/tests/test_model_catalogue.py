import copy

import psycopg
import pytest

from app.features.ingestion.model_index import assemble
from app.features.ingestion.seed import normalize_azure, normalize_catalog, replace_snapshot
from tests.test_run_path import seed_cli


def test_one_model_multiple_providers_and_legacy_contract(
    postgres_client, tmp_path, catalogue, azure_export
):
    assert seed_cli(tmp_path, catalogue, azure_export).returncode == 0
    legacy = postgres_client.get("/api/models").json()
    assert legacy["total"] == 3
    assert postgres_client.get("/api/models?provider=azure").json()["total"] == 2
    page = postgres_client.get("/api/catalogue/models").json()
    assert page["total"] == 2
    model = next(item for item in page["items"] if item["model_id"] == "example/example-one")
    assert model["azure_support"] == "listed"
    assert model["input_price"] == 0
    detail = postgres_client.get(f"/api/catalogue/models/{model['id']}").json()
    assert {item["provider_id"] for item in detail["providers"]} == {"azure", "example"}
    assert len(detail["azure"]) == 1
    assert "provider_id" not in model
    assert postgres_client.get("/api/catalogue/models?azure=listed").json()["total"] == 2
    offering = next(item for item in legacy["items"] if item["provider_id"] == "example")
    assert (
        postgres_client.get(f"/api/catalogue/models/{offering['id']}").json()["id"] == model["id"]
    )
    assert postgres_client.get("/api/catalogue/status").json()["offering_count"] == 3


def test_unreferenced_canonical_and_azure_api_only_models(
    postgres_client, tmp_path, catalogue, azure_export
):
    catalogue["models"]["lab/unreferenced"] = {"name": "Unreferenced", "limit": {"context": 4096}}
    azure_export["locations"]["westus"] = {
        "value": [
            {"model": {"name": "api-only", "version": "1", "format": "OpenAI"}},
            {"model": {"name": "example-one", "version": "1"}},
        ]
    }
    assert seed_cli(tmp_path, catalogue, azure_export).returncode == 0
    page = postgres_client.get("/api/catalogue/models").json()
    assert page["total"] == 4
    orphan = next(item for item in page["items"] if item["model_id"] == "lab/unreferenced")
    assert orphan["azure_support"] == "unknown"
    assert orphan["input_price"] is None
    assert orphan["context_tokens"] == 4096
    api_only = next(item for item in page["items"] if item["model_id"] == "azure/api-only")
    assert api_only["azure_support"] == "listed"
    assert api_only["input_price"] is None
    detail = postgres_client.get(f"/api/catalogue/models/{api_only['id']}").json()
    assert detail["providers"] == []
    shared = next(item for item in page["items"] if item["model_id"] == "example/example-one")
    detail = postgres_client.get(f"/api/catalogue/models/{shared['id']}").json()
    assert {item["location"] for item in detail["azure"]} == {"eastus", "westus"}


def test_variants_do_not_collapse_into_inherited_base(catalogue):
    catalogue["models"]["example/example-one-v2"] = {"name": "Example One v2"}
    catalogue["providers"]["azure"]["models"]["example-one-v2"] = {
        "name": "Example One v2",
        "base_model": "example/example-one",
    }
    _, offerings = normalize_catalog(catalogue)
    specs, links = assemble(catalogue["models"], offerings, [])
    variant = next(row for row in offerings if row[2] == "example-one-v2")
    assert links[variant[0]] == "example/example-one-v2"
    assert "example/example-one" in specs


def test_azure_alias_needs_exact_name_and_publisher_or_family_evidence(catalogue):
    catalogue["models"]["xai/grok-4.20-0309-reasoning"] = {
        "name": "Grok 4.20 (Reasoning)",
        "family": "grok",
    }
    catalogue["providers"]["azure"]["models"]["grok-4-20-reasoning"] = {
        "name": "Grok 4.20 (Reasoning)",
    }
    _, offerings = normalize_catalog(catalogue)
    specs, links = assemble(catalogue["models"], offerings, [])
    offering = next(row for row in offerings if row[2] == "grok-4-20-reasoning")
    assert links[offering[0]] == "xai/grok-4.20-0309-reasoning"
    assert "azure/grok-4-20-reasoning" not in specs


def test_ambiguous_provider_only_aliases_remain_source_metadata(catalogue):
    catalogue["providers"]["example"]["models"]["auto"] = {"name": "Automatic"}
    _, offerings = normalize_catalog(catalogue)
    specs, links = assemble(catalogue["models"], offerings, [])
    alias = next(row for row in offerings if row[2] == "auto")
    assert alias[0] not in links
    assert all(spec.name != "Automatic" for spec in specs.values())


def test_azure_price_pair_has_one_deterministic_source(postgres_client, tmp_path, catalogue):
    catalogue["providers"]["azure-cognitive-services"] = copy.deepcopy(
        catalogue["providers"]["azure"]
    )
    catalogue["providers"]["azure"]["models"]["example-one"]["cost"] = {"input": 5, "output": 1}
    catalogue["providers"]["azure-cognitive-services"]["models"]["example-one"]["cost"] = {
        "input": 1,
        "output": 9,
    }
    assert seed_cli(tmp_path, catalogue).returncode == 0
    item = postgres_client.get("/api/catalogue/models?q=example-one").json()["items"][0]
    assert (item["input_price"], item["output_price"], item["pricing_provider_id"]) == (
        5,
        1,
        "azure",
    )


def test_fallback_identity_survives_canonical_reconciliation(postgres_client, tmp_path, catalogue):
    catalogue["providers"]["azure"]["models"]["future-model"] = {"name": "Future Model"}
    assert seed_cli(tmp_path, catalogue).returncode == 0
    before = postgres_client.get("/api/catalogue/models?q=future-model").json()["items"][0]
    catalogue["models"]["lab/future-model"] = {"name": "Future Model"}
    assert seed_cli(tmp_path, catalogue).returncode == 0
    after = postgres_client.get("/api/catalogue/models?q=future-model").json()["items"]
    assert len(after) == 1
    assert after[0]["id"] == before["id"]
    assert after[0]["model_id"] == "lab/future-model"
    assert postgres_client.get(f"/api/catalogue/models/{before['id']}").status_code == 200


def test_existing_canonical_identity_redirects_old_fallback(postgres_client, tmp_path, catalogue):
    catalogue["models"]["lab/future-model"] = {"name": "Future Model"}
    catalogue["providers"]["azure"]["models"]["future-alias"] = {"name": "Future Alias"}
    assert seed_cli(tmp_path, catalogue).returncode == 0
    old = postgres_client.get("/api/catalogue/models?q=future-alias").json()["items"][0]
    catalogue["providers"]["azure"]["models"]["future-alias"]["base_model"] = "lab/future-model"
    assert seed_cli(tmp_path, catalogue).returncode == 0
    redirected = postgres_client.get(f"/api/catalogue/models/{old['id']}").json()
    assert redirected["model_id"] == "lab/future-model"
    assert redirected["id"] != old["id"]
    assert postgres_client.get("/api/catalogue/models?q=future").json()["total"] == 1


def test_reconciled_alias_can_split_and_merge_again(postgres_client, tmp_path, catalogue):
    catalogue["models"]["lab/future-model"] = {"name": "Future Model"}
    alias = {"name": "Future Alias"}
    catalogue["providers"]["azure"]["models"]["future-alias"] = alias
    assert seed_cli(tmp_path, catalogue).returncode == 0
    models = {
        item["model_id"]: item["id"]
        for item in postgres_client.get("/api/catalogue/models?q=future").json()["items"]
    }
    canonical_id = models["lab/future-model"]
    retired_ids = [models["azure/future-alias"]]
    for _ in range(2):
        alias["base_model"] = "lab/future-model"
        assert seed_cli(tmp_path, catalogue).returncode == 0
        del alias["base_model"]
        result = seed_cli(tmp_path, catalogue)
        assert result.returncode == 0, result.stderr
        models = {
            item["model_id"]: item["id"]
            for item in postgres_client.get("/api/catalogue/models?q=future").json()["items"]
        }
        assert models["lab/future-model"] == canonical_id
        split_id = models["azure/future-alias"]
        assert split_id != canonical_id and split_id not in retired_ids
        for retired_id in retired_ids:
            assert (
                postgres_client.get(f"/api/catalogue/models/{retired_id}").json()["id"]
                == canonical_id
            )
        assert seed_cli(tmp_path, catalogue).returncode == 0
        assert postgres_client.get(f"/api/catalogue/models/{split_id}").json()["id"] == split_id
        retired_ids.append(split_id)


def test_azure_versions_link_only_to_their_explicit_variants(
    postgres_client, tmp_path, catalogue, azure_export
):
    versions = ["2026-01-01", "2026-02-01"]
    for version in versions:
        catalogue["models"][f"example/example-one-{version}"] = {
            "name": f"Example One {version}",
        }
        azure_export["locations"]["eastus"]["value"].append(
            {"model": {"name": "example-one", "version": version}}
        )
    assert seed_cli(tmp_path, catalogue, azure_export).returncode == 0
    page = postgres_client.get("/api/catalogue/models?q=example-one").json()
    assert page["total"] == 3
    for model in page["items"]:
        assert model["azure_support"] == "listed"
        detail = postgres_client.get(f"/api/catalogue/models/{model['id']}").json()
        expected = (
            "1"
            if model["model_id"] == "example/example-one"
            else model["model_id"].removeprefix("example/example-one-")
        )
        assert {item["version"] for item in detail["azure"]} == {expected}


@pytest.mark.parametrize("explicit_provider", ["azure", "azure-cognitive-services"])
def test_shared_azure_alias_uses_trustworthy_association_before_fallback(
    postgres_client, tmp_path, catalogue, explicit_provider
):
    catalogue["providers"]["azure-cognitive-services"] = {
        "name": "Azure Cognitive Services",
        "models": {},
    }
    for provider in ("azure", "azure-cognitive-services"):
        catalogue["providers"][provider]["models"]["endpoint-alias"] = {"name": "Endpoint Alias"}
    catalogue["providers"][explicit_provider]["models"]["endpoint-alias"]["base_model"] = (
        "example/example-one"
    )
    assert seed_cli(tmp_path, catalogue).returncode == 0
    assert postgres_client.get("/api/catalogue/models").json()["total"] == 2
    model = postgres_client.get("/api/catalogue/models?q=example-one").json()["items"][0]
    detail = postgres_client.get(f"/api/catalogue/models/{model['id']}").json()
    aliases = [item for item in detail["providers"] if item["model_id"] == "endpoint-alias"]
    assert {item["provider_id"] for item in aliases} == {"azure", "azure-cognitive-services"}


@pytest.mark.parametrize("preferred_cost", [{}, {"input": 1}])
def test_complete_azure_price_pair_precedes_provider_preference(
    postgres_client, tmp_path, catalogue, preferred_cost
):
    catalogue["providers"]["azure-cognitive-services"] = copy.deepcopy(
        catalogue["providers"]["azure"]
    )
    catalogue["providers"]["azure"]["models"]["example-one"]["cost"] = preferred_cost
    catalogue["providers"]["azure-cognitive-services"]["models"]["example-one"]["cost"] = {
        "input": 0,
        "output": 9,
    }
    assert seed_cli(tmp_path, catalogue).returncode == 0
    model = postgres_client.get("/api/catalogue/models?q=example-one").json()["items"][0]
    assert (model["input_price"], model["output_price"], model["pricing_provider_id"]) == (
        0,
        9,
        "azure-cognitive-services",
    )
    detail = postgres_client.get(f"/api/catalogue/models/{model['id']}").json()
    assert (detail["input_price"], detail["output_price"]) == (0, 9)


def test_api_only_model_links_exact_provider_offering(
    postgres_client, tmp_path, catalogue, azure_export
):
    catalogue["providers"]["example"]["models"]["api-only"] = {"name": "API Only"}
    azure_export["locations"]["eastus"]["value"].append(
        {"model": {"name": "api-only", "version": "1"}}
    )
    assert seed_cli(tmp_path, catalogue, azure_export).returncode == 0
    model = postgres_client.get("/api/catalogue/models?q=api-only").json()["items"][0]
    detail = postgres_client.get(f"/api/catalogue/models/{model['id']}").json()
    assert [item["provider_id"] for item in detail["providers"]] == ["example"]
    assert model["input_price"] is None
    assert (
        postgres_client.get("/api/catalogue/status").json()["sources"]["model_index"][
            "linked_offerings"
        ]
        == 4
    )


def test_complete_enrichment_allows_not_listed_state(postgres_client, catalogue, azure_export):
    catalogue["models"]["lab/not-azure"] = {"name": "Not Azure"}
    providers, offerings = normalize_catalog(catalogue)
    sources = {"azure": {"status": "live", "region_scope": "all_supported_physical_regions"}}
    with psycopg.connect() as connection:
        replace_snapshot(
            connection,
            providers,
            offerings,
            normalize_azure(azure_export),
            sources,
            catalogue["models"],
        )
    item = postgres_client.get("/api/catalogue/models?q=not-azure").json()["items"][0]
    assert item["azure_support"] == "not_listed"
    assert postgres_client.get("/api/catalogue/models?azure=not_listed").json()["total"] == 1


def test_populated_legacy_database_requires_index_refresh(postgres_client, tmp_path, catalogue):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    with psycopg.connect() as connection:
        connection.execute("UPDATE seed_state SET catalogue_count=NULL")
    assert postgres_client.get("/api/models").json()["total"] == 3
    assert postgres_client.get("/api/catalogue/status").status_code == 503
    assert seed_cli(tmp_path, catalogue).returncode == 0
    assert postgres_client.get("/api/catalogue/status").json()["model_count"] == 2


def test_model_index_failure_rolls_back_all_identity_changes(postgres_client, tmp_path, catalogue):
    assert seed_cli(tmp_path, catalogue).returncode == 0
    before = postgres_client.get("/api/catalogue/models").json()
    providers, offerings = normalize_catalog(catalogue)
    with psycopg.connect() as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            replace_snapshot(connection, providers + [providers[0]], offerings, [], {})
    assert postgres_client.get("/api/catalogue/models").json() == before
