# Security policy

## Reporting

For a public repository with private reporting enabled, use
[Report a vulnerability](https://github.com/macromania/model-catalogue/security/advisories/new).
Do not post credentials, exploit details or sensitive logs in a public issue.

If private reporting is unavailable, open an issue asking the maintainer to
arrange a private reporting channel. Include no vulnerability details in that
request. Private vulnerability reporting must be enabled when the repository
is made public; it is not available on the current private repository.

Include the affected commit, reproduction steps, impact and any suggested fix
in the private report. There is no guaranteed response time or commercial
support commitment. Fixes target the current `main` branch; older snapshots
have no maintenance guarantee.

## Deployment boundaries

The optional Azure dashboard intentionally allows anonymous public reads.
Anyone who can reach it can read the catalogue and imported source metadata
through its API proxy. Do not seed confidential data into that deployment.
The backend API ingress, PostgreSQL and Key Vault are private, and the serving
API uses a read-only database role. The manual seed job can write the database.

The local kind dashboard binds to `127.0.0.1`. It is not an authentication
system. Neither deployment is intended to host model inference, accept
untrusted uploads or store user secrets. Protect the Azure subscription and
the machine running the seed program.

## Maintenance checks

CI scans Git history for secrets, audits locked Python/JavaScript dependencies
and exercises the application in kind. Dependabot proposes dependency and
action updates. Automated checks can miss problems and do not certify a
deployment as secure.

If a credential is exposed, revoke or rotate it first. Removing it from the
latest commit does not remove it from Git history, forks, logs or caches.
