# Third-party software and data

The [MIT license](LICENSE) covers this repository's own code and documentation.
It does not replace the licenses or terms of dependencies, imported data,
provider publications, model weights or container base images.

## Catalogue sources

[models.dev](https://github.com/anomalyco/models.dev) publishes its catalogue
under the [MIT license](https://github.com/anomalyco/models.dev/blob/dev/LICENSE).
Preserve its copyright and permission notices when redistributing its data.
The seed program downloads that data at runtime; a full catalogue snapshot is
not committed here.

Azure metadata is retrieved through the user's authorized subscription.
Microsoft service terms and the original providers' terms continue to apply.
Listings, prices and regional observations are dated metadata, not guarantees
of deployment eligibility. Linked model cards and weights retain their own
licenses and are not distributed by this repository.

Files under `examples/` are project-authored synthetic fixtures covered by MIT.
They do not describe real models or Azure service availability.

## Software dependencies

Exact versions are recorded in `backend/uv.lock` and
`frontend/package-lock.json`. Most application dependencies use MIT, BSD,
Apache or ISC licenses. In particular:

| Dependency | License | Upstream |
|---|---|---|
| Psycopg, psycopg-binary and psycopg-pool | LGPL-3.0-only | [Psycopg](https://github.com/psycopg/psycopg) |
| certifi | MPL-2.0 | [certifi](https://github.com/certifi/python-certifi) |
| React and React DOM | MIT | [React](https://github.com/facebook/react) |
| FastAPI | MIT | [FastAPI](https://github.com/fastapi/fastapi) |
| Azure Identity SDK | MIT | [Azure SDK for Python](https://github.com/Azure/azure-sdk-for-python) |

Dependencies are installed separately, not relicensed as project source.
Keep their license files and required notices. When distributing built
containers, also review the licenses and source-availability obligations of
their dependencies and operating-system packages, including LGPL/MPL
components. Follow the upstream source and build instructions when modifying
or redistributing those components. This document is an overview, not an
exhaustive replacement for the licenses bundled with each package.
