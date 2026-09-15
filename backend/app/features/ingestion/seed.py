"""Fetch all upstream data before atomically replacing the local catalogue."""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import psycopg
from azure.core.exceptions import AzureError
from azure.identity import ManagedIdentityCredential
from psycopg.types.json import Jsonb

from app.db import initialize_schema
from app.features.ingestion.model_index import (
    OFFERING_FIELDS,
    assemble,
    identity_ids,
    snapshot_rows,
)
from app.features.ingestion.provenance import azure_provenance
from app.features.ingestion.values import boolean, number, object_value, text

logger = logging.getLogger(__name__)
CATALOG_URL = "https://models.dev/catalog.json"


def now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_catalog(catalog: Any) -> tuple[list[tuple], list[tuple]]:
    catalog = object_value(catalog, "Catalogue")
    providers = object_value(catalog.get("providers"), "Catalogue providers")
    metadata = object_value(catalog.get("models"), "Catalogue models")
    if not providers:
        raise ValueError("Refusing to replace the database with an empty provider catalogue")
    by_suffix: dict[str, list[str]] = defaultdict(list)
    for key, value in metadata.items():
        object_value(value, f"Metadata {key}")
        by_suffix[key.split("/", 1)[-1]].append(key)
    provider_rows, model_rows = [], []
    for provider_id, provider_value in providers.items():
        provider = object_value(provider_value, f"Provider {provider_id}")
        provider_rows.append(
            (provider_id, text(provider.get("name"), provider_id), provider.get("doc"))
        )
        for model_id, model_value in object_value(provider.get("models"), provider_id).items():
            model = object_value(model_value, f"{provider_id}/{model_id}")
            metadata_id, match = None, None
            explicit = model.get("base_model")
            if explicit is not None:
                if explicit not in metadata:
                    raise ValueError(f"Unknown base_model {explicit}")
                metadata_id, match = explicit, "explicit base_model"
            elif model_id in metadata:
                metadata_id, match = model_id, "exact canonical ID"
            elif f"{provider_id}/{model_id}" in metadata:
                metadata_id, match = f"{provider_id}/{model_id}", "exact provider and model ID"
            elif len(by_suffix.get(model_id, [])) == 1:
                metadata_id, match = by_suffix[model_id][0], "unique exact model ID"
            limits = object_value(model.get("limit", {}), f"{model_id}.limit")
            costs = object_value(model.get("cost", {}), f"{model_id}.cost")
            stable_id = uuid5(NAMESPACE_URL, json.dumps([provider_id, model_id]))
            model_rows.append(
                (
                    stable_id,
                    provider_id,
                    model_id,
                    text(model.get("name"), model_id),
                    metadata_id,
                    match,
                    number(limits.get("context"), "context", integer=True),
                    number(limits.get("output"), "output", integer=True),
                    number(costs.get("input"), "input price"),
                    number(costs.get("output"), "output price"),
                    boolean(model.get("reasoning"), "reasoning"),
                    boolean(model.get("tool_call"), "tool_call"),
                    boolean(model.get("open_weights"), "open_weights"),
                    Jsonb(model),
                    Jsonb(metadata[metadata_id]) if metadata_id else None,
                )
            )
    if not model_rows:
        raise ValueError("Refusing to replace the database with an empty model catalogue")
    return provider_rows, model_rows


def normalize_azure(document: Any) -> list[tuple]:
    document = object_value(document, "Azure export")
    locations = object_value(document.get("locations"), "Azure export locations")
    if not locations:
        raise ValueError("Azure export must include at least one location")
    rows = {}
    for location, response in locations.items():
        text(location, "Azure location")
        response = object_value(response, location)
        if response.get("nextLink"):
            raise ValueError(f"{location}: Azure export is incomplete; fetch all nextLink pages")
        entries = response.get("value")
        if not isinstance(entries, list):
            raise ValueError(f"{location}.value must be an array")
        for entry in entries:
            entry = object_value(entry, f"Azure model in {location}")
            model = object_value(entry.get("model", entry), "Azure model")
            name = text(model.get("name"), "Azure model name")
            version = model.get("version", "")
            if not isinstance(version, str):
                raise ValueError("Azure model version must be a string")
            # Regional lists can repeat a model/version for different account SKUs.
            key = (location, name, version)
            if key in rows:
                rows[key]["entries"].append(entry)
            else:
                rows[key] = {"entries": [entry]}
    return [(*key, Jsonb(value)) for key, value in rows.items()]


def azure_document(
    client: httpx.Client, url: str, token: str, authorization_retries: int = 0
) -> dict:
    for attempt in range(authorization_retries + 1):
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 403 and attempt < authorization_retries:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict) and error.get("code") == "AuthorizationFailed":
                delay = min(2 ** (attempt + 1), 30)
                logger.warning(
                    "Azure authorization has not propagated; retry %s/%s in %s seconds.",
                    attempt + 1,
                    authorization_retries,
                    delay,
                )
                time.sleep(delay)
                continue
        response.raise_for_status()
        return object_value(response.json(), "Azure response")
    raise RuntimeError("Azure authorization retry budget was exhausted")


def azure_items(client: httpx.Client, url: str, token: str, authorization_retries: int = 0) -> list:
    values, seen = [], set()
    while url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "management.azure.com":
            raise ValueError("Azure pagination link points outside management.azure.com")
        if url in seen:
            raise ValueError("Azure pagination loop detected")
        seen.add(url)
        page = azure_document(client, url, token, authorization_retries)
        if not isinstance(page.get("value"), list):
            raise ValueError("Azure response is missing its value array")
        values.extend(page["value"])
        url = page.get("nextLink")
    return values


def fetch_azure(
    client: httpx.Client,
    subscription: str,
    regions: list[str],
    managed_identity_client_id: str | None = None,
) -> dict:
    UUID(subscription)
    if not regions or any(not re.fullmatch(r"[a-z0-9]+", region) for region in regions):
        raise ValueError("AZURE_REGIONS must be comma-separated Azure location IDs")
    if "all" in regions and regions != ["all"]:
        raise ValueError("Use AZURE_REGIONS=all by itself, not mixed with explicit locations")
    if managed_identity_client_id:
        UUID(managed_identity_client_id)
        with ManagedIdentityCredential(client_id=managed_identity_client_id) as credential:
            token = credential.get_token("https://management.azure.com/.default").token
    else:
        token_result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--subscription",
                subscription,
                "--resource",
                "https://management.azure.com/",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        token = text(json.loads(token_result.stdout).get("accessToken"), "Azure access token")
    result = {"locations": {}, "api_version": "2024-10-01"}
    authorization_retries = 8 if managed_identity_client_id else 0
    if regions == ["all"]:
        locations = azure_items(
            client,
            f"https://management.azure.com/subscriptions/{subscription}/locations?api-version=2022-12-01",
            token,
            authorization_retries,
        )
        physical = []
        aliases = {}
        for item in locations:
            location = object_value(item, "Azure location")
            name = text(location.get("name"), "Azure location name")
            aliases[name.casefold()] = name
            aliases[text(location.get("displayName", name), "Azure display name").casefold()] = name
            if (
                location.get("type") == "Region"
                and object_value(location.get("metadata", {}), "Azure location metadata").get(
                    "regionType"
                )
                == "Physical"
            ):
                physical.append(name)
        if not physical:
            raise ValueError("Azure region discovery returned no physical regions")
        provider = azure_document(
            client,
            f"https://management.azure.com/subscriptions/{subscription}/providers/Microsoft.CognitiveServices?api-version=2021-04-01",
            token,
            authorization_retries,
        )
        resource_types = provider.get("resourceTypes")
        if not isinstance(resource_types, list):
            raise ValueError("Azure provider discovery is missing resourceTypes")
        model_types = [
            item
            for item in resource_types
            if isinstance(item, dict)
            and isinstance(item.get("resourceType"), str)
            and item["resourceType"].casefold() == "locations/models"
        ]
        if len(model_types) != 1 or result["api_version"] not in model_types[0].get(
            "apiVersions", []
        ):
            raise ValueError("Azure no longer advertises the configured model-list API contract")
        supported = model_types[0].get("locations")
        if not isinstance(supported, list) or not supported:
            raise ValueError("Azure model-list discovery returned no supported locations")
        resolved = []
        non_physical = []
        for item in supported:
            label = text(item, "Azure supported location").casefold()
            if label == "global":
                non_physical.append("global")
            elif label in aliases:
                if aliases[label] in physical:
                    resolved.append(aliases[label])
                else:
                    non_physical.append(aliases[label])
            else:
                raise ValueError(f"Cannot resolve the model-list location {item!r}")
        regions = sorted(set(resolved))
        if any(not re.fullmatch(r"[a-z0-9]+", region) for region in regions):
            raise ValueError("Azure region discovery returned an invalid region name")
        result["region_scope"] = "all_supported_physical_regions"
        result["discovered_physical_regions"] = sorted(set(physical))
        result["unsupported_locations"] = sorted(set(physical) - set(regions))
        result["non_physical_locations"] = sorted(set(non_physical))
        logger.info(
            "Querying all %s advertised catalogue locations; %s physical regions do not support this API.",
            len(regions),
            len(result["unsupported_locations"]),
        )
    else:
        result["region_scope"] = "explicit"
    for region in regions:
        url = (
            f"https://management.azure.com/subscriptions/{subscription}/providers/"
            f"Microsoft.CognitiveServices/locations/{quote(region)}/models?api-version=2024-10-01"
        )
        result["locations"][region] = {
            "value": azure_items(client, url, token, authorization_retries)
        }
    result["empty_locations"] = [
        region for region, response in result["locations"].items() if not response["value"]
    ]
    result["fetched_at"] = now()
    return result


def replace_snapshot(
    connection, provider_rows, model_rows, azure_rows, sources, canonical_metadata=None
):
    if canonical_metadata is None:
        canonical_metadata = {
            row[4]: row[14].obj for row in model_rows if row[4] is not None and row[14] is not None
        }
    specs, links = assemble(canonical_metadata, model_rows, azure_rows)
    with connection.transaction():
        initialize_schema(connection)
        identities = identity_ids(connection, specs)
        catalogue_rows = snapshot_rows(specs, identities, sources)
        connection.execute("DELETE FROM models")
        connection.execute("DELETE FROM providers")
        connection.execute("DELETE FROM azure_models")
        connection.execute("DELETE FROM catalogue_models")
        with connection.cursor() as cursor:
            cursor.executemany("INSERT INTO providers VALUES (%s, %s, %s)", provider_rows)
            cursor.executemany(
                """INSERT INTO catalogue_models (
                    id,model_id,name,publisher,context_tokens,output_tokens,input_price,
                    output_price,reasoning,tool_call,open_weights,azure_support,
                    pricing_provider_id,azure_names,raw,metadata,azure_observations
                ) VALUES ("""
                + ", ".join(["%s"] * 17)
                + ")",
                catalogue_rows,
            )
            cursor.executemany(
                "INSERT INTO models ("
                + ", ".join(OFFERING_FIELDS)
                + ", catalogue_id) VALUES ("
                + ", ".join(["%s"] * 16)
                + ")",
                [
                    (*row, identities[links[row[0]]] if row[0] in links else None)
                    for row in model_rows
                ],
            )
            cursor.executemany("INSERT INTO azure_models VALUES (%s, %s, %s, %s)", azure_rows)
        sources["model_index"] = {
            "canonical_source_models": len(canonical_metadata),
            "models": len(catalogue_rows),
            "linked_offerings": len(links),
            "unlinked_offerings": len(model_rows) - len(links),
        }
        connection.execute(
            """INSERT INTO seed_state (id,seeded_at,model_count,sources,catalogue_count)
               VALUES (1, now(), %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET seeded_at = excluded.seeded_at,
                   model_count = excluded.model_count, sources = excluded.sources,
                   catalogue_count = excluded.catalogue_count""",
            [len(model_rows), Jsonb(sources), len(catalogue_rows)],
        )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-file", type=Path)
    parser.add_argument("--azure-file", type=Path)
    parser.add_argument("--azure-subscription", default=os.getenv("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--azure-regions", default=os.getenv("AZURE_REGIONS", ""))
    parser.add_argument(
        "--managed-identity-client-id", default=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID")
    )
    args = parser.parse_args()
    if args.azure_file and (args.azure_subscription or args.azure_regions):
        parser.error("Use either --azure-file or live Azure configuration, not both")
    if bool(args.azure_subscription) != bool(args.azure_regions):
        parser.error("Live enrichment requires both AZURE_SUBSCRIPTION_ID and AZURE_REGIONS")
    if args.managed_identity_client_id and not args.azure_subscription:
        parser.error("Managed identity requires an explicit Azure subscription and regions")
    return args


def load_snapshot(args):
    with httpx.Client(
        timeout=60, follow_redirects=False, headers={"User-Agent": "model-catalogue/0.1"}
    ) as client:
        if args.catalog_file:
            content = args.catalog_file.read_bytes()
        else:
            response = client.get(CATALOG_URL)
            response.raise_for_status()
            content = response.content
        catalogue = json.loads(content)
        provider_rows, model_rows = normalize_catalog(catalogue)
        sources = {
            "models_dev": {
                "url": CATALOG_URL,
                "mode": "file" if args.catalog_file else "live",
                "imported_at": now(),
                "fetched_at": None if args.catalog_file else now(),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            "azure": {"status": "not_configured", "locations": [], "count": 0},
        }
        azure_rows = []
        if args.azure_file or args.azure_subscription:
            document = (
                json.loads(args.azure_file.read_bytes())
                if args.azure_file
                else fetch_azure(
                    client,
                    args.azure_subscription,
                    args.azure_regions.split(","),
                    args.managed_identity_client_id,
                )
            )
            azure_rows = normalize_azure(document)
            sources["azure"] = {
                "status": "file" if args.azure_file else "live",
                "imported_at": now(),
                "locations": list(document["locations"]),
                "count": len(azure_rows),
                "region_scope": document.get("region_scope", "file"),
                "discovered_physical_regions": document.get("discovered_physical_regions", []),
                "unsupported_locations": document.get("unsupported_locations", []),
                "non_physical_locations": document.get("non_physical_locations", []),
                "empty_locations": [
                    region
                    for region, response in document["locations"].items()
                    if not response["value"]
                ],
                **azure_provenance(document),
            }
        else:
            logger.warning(
                "Azure enrichment is not configured; Azure availability remains unknown."
            )
    return provider_rows, model_rows, azure_rows, sources, catalogue["models"]


def main():
    args = parse_args()
    snapshot = load_snapshot(args)
    with psycopg.connect() as connection:
        replace_snapshot(connection, *snapshot)
    logger.info(
        "Seeded %s provider offerings and %s Azure records; indexed %s models.",
        len(snapshot[1]),
        len(snapshot[2]),
        snapshot[3]["model_index"]["models"],
    )


def cli():
    try:
        main()
    except (
        ValueError,
        OSError,
        httpx.HTTPError,
        psycopg.Error,
        subprocess.CalledProcessError,
        AzureError,
    ) as error:
        logger.error("Seed failed; the previous snapshot was not replaced: %s", error)
        raise SystemExit(1) from error
