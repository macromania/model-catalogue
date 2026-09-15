"""Model identities are separate from provider endpoints and survive snapshot replacement."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb

from app.contracts import AZURE_PROVIDERS
from app.features.ingestion.values import boolean, number, object_value, text

OFFERING_FIELDS = (
    "id",
    "provider_id",
    "model_id",
    "name",
    "metadata_id",
    "metadata_match",
    "context_tokens",
    "output_tokens",
    "input_price",
    "output_price",
    "reasoning",
    "tool_call",
    "open_weights",
    "raw",
    "metadata",
)


@dataclass
class ModelSpec:
    key: str
    name: str
    metadata: dict[str, Any] | None
    publisher: str | None = None
    aliases: set[str] = field(default_factory=set)
    azure_names: set[str] = field(default_factory=set)
    azure_observations: set[tuple[str, str]] = field(default_factory=set)
    azure_offerings: list[dict[str, Any]] = field(default_factory=list)
    api_raw: dict[str, Any] | None = None


def assemble(canonical: dict, offerings: list[tuple], azure_rows: list[tuple]):
    specs: dict[str, ModelSpec] = {}
    tails: dict[str, set[str]] = defaultdict(set)
    names: dict[str, set[str]] = defaultdict(set)
    for key, value in canonical.items():
        metadata = object_value(value, f"Canonical model {key}")
        spec = ModelSpec(
            key,
            text(metadata.get("name"), key),
            metadata,
            publisher=key.split("/", 1)[0] if "/" in key else None,
            aliases={key},
        )
        specs[key] = spec
        tails[key.split("/", 1)[-1]].add(key)
        names[spec.name.casefold()].add(key)
    records = [dict(zip(OFFERING_FIELDS, row, strict=True)) for row in offerings]
    links: dict[UUID, str] = {}
    azure_ids: dict[str, set[str]] = defaultdict(set)

    for item in records:
        model_id, provider = item["model_id"], item["provider_id"]
        key = None
        # Explicit catalogue variants take precedence over inherited base metadata.
        for candidate in (model_id, f"{provider}/{model_id}"):
            if candidate in specs:
                key = candidate
                break
        if key is None and len(tails[model_id]) == 1:
            key = next(iter(tails[model_id]))
        if key is None and item["metadata_id"] in specs:
            key = item["metadata_id"]
        if key is None and provider in AZURE_PROVIDERS:
            candidates = names[item["name"].casefold()]
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                publisher = specs[candidate].publisher
                family = (specs[candidate].metadata or {}).get("family")
                prefixes = [
                    value.casefold()
                    for value in (publisher, family)
                    if isinstance(value, str) and value
                ]
                if any(model_id.casefold().startswith(f"{prefix}-") for prefix in prefixes):
                    key = candidate
        if key is not None:
            links[item["id"]] = key
            if provider in AZURE_PROVIDERS:
                azure_ids[model_id.casefold()].add(key)

    canonical_names: dict[str, set[str]] = defaultdict(set)
    for key in canonical:
        canonical_names[key.casefold()].add(key)
        canonical_names[key.split("/", 1)[-1].casefold()].add(key)
    for _, name, version, wrapped in azure_rows:
        identifier = name.casefold()
        qualified = f"{identifier}-{version.casefold()}"
        version_candidates = (
            azure_ids[qualified] or canonical_names[qualified] if version else set()
        )
        if version_candidates:
            identifier, candidates = qualified, version_candidates
        else:
            candidates = azure_ids[identifier] or canonical_names[identifier]
        key = next(iter(candidates)) if len(candidates) == 1 else f"azure/{identifier}"
        entries = wrapped.obj.get("entries", [])
        entry = entries[0] if entries else {}
        raw = object_value(entry.get("model", entry), f"Azure model {name}")
        specs.setdefault(
            key,
            ModelSpec(
                key, name, None, publisher=raw.get("publisher") or raw.get("format"), aliases={key}
            ),
        )
        specs[key].azure_names.add(name)
        specs[key].azure_observations.add((name, version))
        specs[key].aliases.add(f"azure/{identifier}")
        specs[key].api_raw = raw
        if specs[key].publisher is None:
            specs[key].publisher = raw.get("publisher") or raw.get("format")
        azure_ids[identifier].add(key)

    # Resolve shared Azure endpoints before creating any provider-only fallback.
    for item in records:
        if item["id"] in links or item["provider_id"] not in AZURE_PROVIDERS:
            continue
        identifier = item["model_id"].casefold()
        if not azure_ids[identifier]:
            key = f"azure/{identifier}"
            specs.setdefault(key, ModelSpec(key, item["name"], None, aliases={key}))
            azure_ids[identifier].add(key)

    for item in records:
        candidates = azure_ids[item["model_id"].casefold()]
        if item["id"] not in links and len(candidates) == 1:
            links[item["id"]] = next(iter(candidates))
        key = links.get(item["id"])
        if key is not None and item["provider_id"] in AZURE_PROVIDERS:
            specs[key].azure_offerings.append(item)
            specs[key].aliases.add(f"azure/{item['model_id'].casefold()}")
    return specs, links


def identity_ids(connection, specs: dict[str, ModelSpec]) -> dict[str, UUID]:
    existing = dict(
        connection.execute("SELECT model_key, model_id FROM catalogue_model_keys").fetchall()
    )
    alias_owners: dict[str, set[str]] = defaultdict(set)
    for key, spec in specs.items():
        for alias in spec.aliases:
            alias_owners[alias].add(key)
    previous_models = dict(
        connection.execute("SELECT id,model_id FROM catalogue_models").fetchall()
    )
    claims: dict[UUID, list[str]] = defaultdict(list)
    for key in specs:
        if key in existing:
            claims[existing[key]].append(key)
    reserved = {
        model_id: min(
            keys,
            key=lambda key: (
                specs[key].metadata is None,
                previous_models.get(model_id) != key,
                key,
            ),
        )
        for model_id, keys in claims.items()
    }
    retired = {
        row[0]
        for row in connection.execute("SELECT source_id FROM catalogue_model_redirects").fetchall()
    }
    unavailable = set(existing.values()) | retired
    ids: dict[str, UUID] = {}
    for key, spec in sorted(specs.items()):
        candidate = existing.get(key)
        if candidate is not None and reserved[candidate] != key:
            candidate = None
        if candidate is None:
            candidates = [
                existing[alias]
                for alias in sorted(spec.aliases)
                if alias in existing
                and len(alias_owners[alias]) == 1
                and existing[alias] not in ids.values()
                and existing[alias] not in retired
                and (existing[alias] not in reserved or reserved[existing[alias]] == key)
            ]
            if candidates:
                candidate = candidates[0]
            else:
                candidate = uuid5(NAMESPACE_URL, f"catalogue-model:{key}")
                generation = 0
                # Retired bookmarks must keep redirecting, not become a split model.
                while candidate in unavailable:
                    generation += 1
                    candidate = uuid5(NAMESPACE_URL, f"catalogue-model:{key}:split:{generation}")
        if candidate in ids.values():
            raise ValueError(f"Ambiguous persistent model identity for {key}")
        ids[key] = candidate
        unavailable.add(candidate)
    active_ids = set(ids.values())
    for key, spec in specs.items():
        model_id = ids[key]
        for alias in sorted(spec.aliases):
            if len(alias_owners[alias]) != 1:
                continue
            previous = existing.get(alias)
            if previous is not None and previous != model_id and previous not in active_ids:
                connection.execute(
                    "UPDATE catalogue_model_keys SET model_id=%s WHERE model_id=%s",
                    [model_id, previous],
                )
                connection.execute(
                    "UPDATE catalogue_model_redirects SET target_id=%s WHERE target_id=%s",
                    [model_id, previous],
                )
                connection.execute(
                    """INSERT INTO catalogue_model_redirects VALUES (%s,%s)
                       ON CONFLICT (source_id) DO UPDATE SET target_id=excluded.target_id""",
                    [previous, model_id],
                )
                existing = {k: model_id if v == previous else v for k, v in existing.items()}
            connection.execute(
                """INSERT INTO catalogue_model_keys VALUES (%s,%s)
                   ON CONFLICT (model_key) DO UPDATE SET model_id=excluded.model_id""",
                [alias, model_id],
            )
            existing[alias] = model_id
    return ids


def snapshot_rows(specs: dict[str, ModelSpec], ids: dict[str, UUID], sources: dict):
    rows = []
    complete = (
        sources.get("azure", {}).get("status") in {"live", "file"}
        and sources.get("azure", {}).get("region_scope") == "all_supported_physical_regions"
    )
    for key, spec in specs.items():
        metadata = spec.metadata or {}
        preferred = min(
            spec.azure_offerings,
            key=lambda item: (
                (item["input_price"] is None) + (item["output_price"] is None),
                item["provider_id"] != "azure",
                item["model_id"],
            ),
            default=None,
        )
        raw = preferred["raw"].obj if preferred else metadata or spec.api_raw or {"name": spec.name}
        limits = object_value(metadata.get("limit", {}), f"{key}.limit")
        context = preferred["context_tokens"] if preferred else None
        output = preferred["output_tokens"] if preferred else None
        support = (
            "listed" if preferred or spec.azure_names else "not_listed" if complete else "unknown"
        )
        rows.append(
            (
                ids[key],
                key,
                preferred["name"] if preferred and spec.metadata is None else spec.name,
                spec.publisher,
                context
                if context is not None
                else number(limits.get("context"), key, integer=True),
                output if output is not None else number(limits.get("output"), key, integer=True),
                preferred["input_price"] if preferred else None,
                preferred["output_price"] if preferred else None,
                boolean(raw.get("reasoning", metadata.get("reasoning")), key),
                boolean(raw.get("tool_call", metadata.get("tool_call")), key),
                boolean(metadata.get("open_weights", raw.get("open_weights")), key),
                support,
                preferred["provider_id"] if preferred else None,
                sorted(spec.azure_names),
                Jsonb(raw),
                Jsonb(spec.metadata) if spec.metadata else None,
                Jsonb(
                    [
                        {"model_name": name, "version": version}
                        for name, version in sorted(spec.azure_observations)
                    ]
                ),
            )
        )
    return rows
