# Model catalogue

A small, read-only model dashboard running in a local kind cluster. PostgreSQL stores the snapshot, FastAPI reads it, and a React/Vite SPA displays it. A separate Python program imports models.dev and optional Azure metadata.

No application login is implemented. The local UI is published on **127.0.0.1 only**. The Azure HTTPS dashboard is intentionally **public without login or IP restrictions**, so anyone with the URL can read the catalogue through the UI and its API proxy. The backend API ingress, PostgreSQL and Key Vault remain private.

## Quick start

Prerequisites: Docker Desktop on macOS or Docker Engine on Linux, running Linux containers; kind, kubectl, make, POSIX sh, curl, jq, OpenSSL, netcat (`nc`), and uv. The seed program needs Python 3.12+; uv manages its environment. Use Node 22/npm and `shasum` for host-side verification and frontend development. Container builds use Node 22 and Python 3.14. CI exercises Linux; native Windows shell workflows are not supported.

```bash
git clone https://github.com/macromania/model-catalogue.git
cd model-catalogue
make up
make seed
```

Open **http://127.0.0.1:18420**.

Run `make` for grouped help. Terminal output uses restrained emphasis only on a terminal, respects `NO_COLOR`, and keeps captured output plain.

`make up` builds images, creates a dedicated `model-catalogue` kind cluster if needed, loads the images, deploys the three services and waits for readiness. It uses `.local/kubeconfig` and does not switch your normal kubectl context. Ownership records bind the checkout to the exact control-plane container and Docker context. Shell scripts, not Python, implement the Make workflow.

`make seed` downloads the current combined models.dev catalogue and replaces the database snapshot in one transaction. Repeating it does not duplicate offerings. The API and UI never call models.dev or Azure themselves.

An unseeded installation displays instructions rather than fake data. Refresh the browser view after seeding. `make up` can be rerun after code changes without reseeding or deleting PostgreSQL data.

For a demonstration or CI run that does not fetch upstream catalogue data:

```bash
CATALOG_FILE=examples/catalogue.json AZURE_FILE=examples/azure-models.json make seed
```

These fixtures contain **synthetic models and Azure observations**, not real
availability claims. No Azure account is needed. As with every seed, this
replaces the existing snapshot. Container images and dependencies still need
to be downloaded on first setup.

## Azure enrichment

Azure provider entries in models.dev are imported by default. They are **not** a live Azure availability check. Without an Azure import, the UI explicitly says "Azure: not checked".

For a read-only live import, sign in locally with Azure CLI, then choose the subscription and regions:

```bash
az login
AZURE_SUBSCRIPTION_ID="<subscription-uuid>" \
AZURE_REGIONS="all" make seed
```

Both variables are required. The seed program obtains a short-lived management token from the local CLI, follows Azure pagination, and stores model metadata only. Azure tokens are not stored in PostgreSQL or passed into Kubernetes.

`all` discovers the subscription's physical regions and the model-list API's advertised locations, then queries every supported physical region, including empty results. Physical regions that do not support this API are recorded separately in coverage metadata, not silently called empty. Logical geography labels are not deployment regions; Azure advertises a Global entry but rejects it on the regional model-list endpoint, so it is recorded separately rather than queried. Use a comma-separated list such as `eastus,uaenorth` only when you deliberately want narrower coverage. The cloud seed job defaults to `all` as well.

Alternatively, import a complete regional export:

```bash
AZURE_FILE="/absolute/path/to/azure-models.json" make seed
```

The file accepts the regional model-list response shape, wrapped by location:

```json
{
  "fetched_at": "2026-09-14T12:00:00Z",
  "api_version": "2024-10-01",
  "locations": {
    "eastus": {
      "value": [
        {
          "model": {
            "name": "your-model-id",
            "version": "your-version",
            "lifecycleStatus": "GenerallyAvailable",
            "skus": [{"name": "GlobalStandard"}]
          }
        }
      ]
    }
  }
}
```

This example describes the shape, not a real availability claim. Collect every page first; file imports with a remaining `nextLink` are rejected. Account-model responses can also be supplied as direct model objects in each `value` array.

`fetched_at` and `api_version` are optional provenance supplied by the exporter, not inferred from import time. Missing values remain unknown; `imported_at` is recorded separately. Both `azure` and `azure-cognitive-services` offerings can be enriched by exact model ID.

`CATALOG_FILE="/absolute/path/to/catalog.json" make seed` uses an existing models.dev combined export instead of downloading it. It can be combined with `AZURE_FILE`.

A refresh is a **complete replacement**. Running without Azure configuration clears prior Azure observations and marks them unchecked. An upstream fetch, validation or database-write failure leaves the old snapshot intact.

## Interface

Search by name, model ID or publisher. Filter by Azure listing evidence or reasoning support, sort limits/Azure prices, page through results, and compare up to three models. Model details include modalities, capabilities, benchmarks, Azure observations, provider listings, pricing tiers and raw source properties.

The main list contains **models**, not provider offerings. It uses every model in the model-only catalogue plus distinct Azure-only models observed in provider or regional API data. Explicit variants remain separate. Provider listings are retained in model details; ambiguous provider-only aliases without a trustworthy model identity remain stored as source data rather than becoming duplicate master rows.

An Azure tick means the model appears in synced Azure listings or API observations. A cross means it was not found in the complete synced sources; a question mark means the check is incomplete. These indicators do not guarantee quota or deployment permission. Regional observations match explicit name/version variants before the base model, and details include only the associated versions. Main-list prices come from one deterministic Azure offering. Complete price pairs rank above partial or missing prices, then `azure` is preferred over `azure-cognitive-services`. Prices never combine independent minima or non-Azure providers.

Model identity keys and redirects survive snapshot refreshes. When an Azure-only entry gains a canonical identity, its old model ID remains usable or redirects to the surviving model. If that association later splits, the canonical identity stays stable and the separated alias receives a distinct ID. Retired bookmarks continue to redirect rather than being reused. Existing offering UUIDs are preserved as source records.

Prices are reported base USD rates per million tokens, not negotiated Azure quotes. Raw records retain cache and context tiers. Missing values are distinct from zero and false. Benchmark scores retain source, version, harness and variant where supplied; they are not independent local measurements.

## Vertical slices

Each feature owns its behavior rather than sharing generic controller/service/repository layers:

```text
backend/app/
  main.py                       Application composition, health and DB lifecycle
  seed.py                       CLI composition
  contracts.py, db.py            Small shared contracts/infrastructure
  features/
    catalogue/models.py         Master model listing, filters and snapshot status
    catalogue/routes.py         Legacy offering list, providers and status
    model_details/models.py     Model details, provider metadata and ID redirects
    model_details/routes.py     Legacy offering details and source observations
    ingestion/seed.py           Fetch, normalization and atomic replacement
    ingestion/model_index.py    Model identities and provider/Azure linkage
backend/tests/                  Shared PostgreSQL fixtures and run-path tests

frontend/src/
  App.tsx                       Application shell and slice composition
  features/
    catalogue/                  Search, filters, results, pagination and browser tests
    model-details/              Model details, providers and benchmarks
    comparison/                 Selected-model comparison
  shared/                       HTTP contract, formatting, navigation and primitives
  index.css                     Plain shared design tokens and layout rules
```

The model API is under `/api/catalogue/models` and `/api/catalogue/status`. Legacy `/api/models`, `/api/providers` and `/api/status` offering contracts remain available during migration. The seed path adds the model index before the new API/UI is deployed, and cloud reader grants cover the new tables in the same transaction as snapshot replacement.

Queries stay beside their endpoint. Feature UI and behavior stay together. Shared code is limited to genuinely reused contracts, infrastructure and primitives.

## Verification

```bash
make test
make verify
```

`make test` checks shell syntax, Python lint/unit tests and frontend lint, type checking, production build and unit tests. `make verify` prepares the frontend/browser dependencies, runs real PostgreSQL run-path tests in isolated temporary schemas, compares the running API source files with the checkout, builds the current frontend and byte-compares its index/JS/CSS with deployed assets, then runs desktop/mobile browser tests.

Shell regression tests use isolated Docker/Kubernetes command stubs. They do not delete or modify a real cluster.

Verification also cancels a temporary tunnel wrapper with a TERM-resistant test child and checks that the wrapper, child processes and tunnel stop promptly. Normal command exit codes and signal-specific failures are preserved. Source enumeration and hashing errors fail verification instead of producing an empty successful check.

Integration tests do not overwrite the catalogue schema. They invoke the actual seed CLI and actual HTTP routes, and check repeat seeding, failure rollback, filtering, details and pagination.

Browser smoke tests choose records from the current API, so small/offline catalogues are supported. UI edge-case and comparison tests use browser-local intercepted fixtures and never replace the user's database.

GitHub Actions runs these checks in kind on Linux using only synthetic data.
It also scans Git history for secrets, audits locked dependencies and compiles
the Azure templates without cloud credentials. CI never deploys to Azure.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor workflow and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Local operations

```bash
make logs
make down
```

**`make down` deletes the verified dedicated kind cluster and its PostgreSQL volume.** Pod restarts and `make up` preserve data; cluster deletion does not. Seed again after recreating the cluster. Teardown does not depend on namespace/API health and succeeds if the cluster is already absent.

The generated database password, ownership record and kubeconfig live under ignored `.local/`. Do not delete or edit the password file while its database volume still exists. Reruns reject missing, changed or whitespace-padded credentials before updating any Kubernetes Secret. No implicit password rotation is performed.

Reserved ports are recorded in `ports.env`: UI host port 18420, API internal port 18421, temporary DB tunnel host port 18422, optional Vite host port 18423. The host ports can be configured; the API container port, UI container port 18420 and NodePort 30420 are fixed. The API and database have ClusterIP services only. Scripts refuse occupied local ports, credential drift and unrelated same-named clusters.

Playwright and Vite read the same port configuration. Changing the host UI port of an existing cluster requires `make down` followed by `make up`. Make command-line port overrides must be passed consistently to subsequent commands; editing `ports.env` makes the choice persistent.

For frontend development while kind is running:

```bash
make dev-ui
```

Vite runs on 127.0.0.1:18423 and proxies API requests through the local cluster's UI service.

## Azure Container Apps

The Azure workflow uses the currently signed-in Azure CLI subscription on first use and records it under ignored `.local/azure/`. Subsequent commands reject a different signed-in subscription. The default deployment is a dedicated `rg-model-catalogue-dev-swc` resource group in Sweden Central.

```bash
make azure-prepare
make azure-validate
make azure-deploy
make azure-verify
```

Azure prerequisites include an account allowed to create resources and role assignments, Azure CLI with the Container Apps extension and Bicep, Docker with Linux amd64 support, Node/npm, and the existing shell tools. Deployment images require a clean committed worktree. The workflow inspects actual image contents, pushes to ACR and deploys immutable digests.

This creates a Consumption Container Apps environment, a public HTTPS frontend, an internal API, a manual seed job, private PostgreSQL Flexible Server B1ms, a private network/DNS zone, Key Vault, managed identities and monitoring resources. The UI and API each have **minReplicas=1 and maxReplicas=1**, so neither scales to zero. Rollout overlap can temporarily create another replica; one instance is not high availability. The seed job remains manual. PostgreSQL, ACR and always-on apps incur ongoing charges. The API uses a separate read-only database role; the initializer owns schema and snapshot writes.

On first preparation, set `AZURE_LOCATION`, `AZURE_RESOURCE_GROUP` and `AZURE_REGIONS` if the defaults are unsuitable. The dashboard has no IP allowlist or blocklist. Preparation removes the obsolete `allowedCidr` field from older local deployment contexts. Other configuration changes to an existing deployment must be made deliberately in `.local/azure/context.json`.

Key Vault stays private behind its own private endpoint and DNS zone. After bootstrap, deployments use ARM Key Vault parameter references rather than reading passwords onto the operator's machine or replacing them from a local file. The operator needs `Microsoft.KeyVault/vaults/deploy/action`; template access is explicitly enabled on this application's vault. A partially completed bootstrap can use its preserved credentials only before the database exists. `make azure-repair-network` validates and repairs this project's private vault route without enabling public access.

```bash
make azure-seed
make azure-status
```

`make azure-update` rebuilds and verifies application images, reruns the seed job and updates the apps without reprovisioning the foundation. The nginx proxy uses verified upstream TLS and HTTP/1.1 for Container Apps ingress.

`make azure-configure` validates and applies only the app configuration using the stored immutable image references. It does not rebuild images, run the seed job or redeploy the foundation. Use it to apply ingress or replica settings to an existing deployment, then run `make azure-verify`.

Cloud seeding uses only its explicit managed identity, subscription and region configuration. It rejects missing Azure configuration rather than clearing metadata. A database-backed guard prevents overlapping jobs, and the data replacement and reader-role setup share one transaction.

`make azure-verify` requires the exact successful seed execution and intended healthy serving revisions, checks public HTTPS ingress without IP rules or platform authentication, confirms private API/PostgreSQL/Key Vault access, and runs browser tests against the cloud URL. Application request logs go to Log Analytics; the Application Insights resource is provisioned for later tracing integration, but this spike does not claim SDK-level tracing.

If Apple Make is blocked by an unaccepted Xcode licence, the same operations can be run as `sh scripts/azure.sh prepare`, `validate`, `deploy`, `update`, `configure`, `seed`, `status`, or `verify`. Local shell entrypoints require the exported values from `ports.env`. The project does not accept platform licences on your behalf.

There is no automatic Azure teardown. Deleting the dedicated resource group removes the database and app resources, subject to Key Vault retention. The custom subscription-level model-reader role and assignment also need explicit cleanup. Review those resources before deleting anything.

## Scope and sources

This is a development spike, not a production platform. There is no scheduled sync, model inference/deployment control, user-account management, or general model-card scraping. Azure metadata covers only imported regions and exact IDs. It does not guarantee quota, capacity, permissions or complete Foundry portal parity.

Primary sources: [models.dev](https://models.dev), [its MIT-licensed database](https://github.com/anomalyco/models.dev), and [Azure's regional model-list API](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/models/list). Linked provider publications and model weights retain their own terms.

## License and maintenance

Project code and documentation are licensed under [MIT](LICENSE).
[Third-party notices](THIRD_PARTY_NOTICES.md) explain the separate terms for
dependencies, catalogue data and model publications. Public source code does
not imply a support or service-availability guarantee.

Contributions are welcome through issues and pull requests. Maintainers
should follow the [release checklist](docs/maintaining.md) before changing
repository visibility or publishing container images.