# Contributing

This is a small development project, not a supported production service. Bug
reports, documentation corrections and focused pull requests are welcome.
Discuss substantial behavior or architecture changes in an issue first.

## Development

Use macOS with Docker Desktop or Linux with Docker Engine. Docker must run
Linux containers. Windows users need a Linux environment such as WSL2; native
Windows shell commands are not supported.

Install the tools listed in the [README](README.md#quick-start). Python
dependencies are managed by uv; frontend dependencies use npm. Keep `uv.lock`
and `package-lock.json` in sync with their manifests. Do not edit lockfiles
by hand.

```sh
make up
CATALOG_FILE=examples/catalogue.json AZURE_FILE=examples/azure-models.json make seed
make test
make verify
```

The example records are synthetic, not real model or Azure availability
claims. No Azure account is needed. Seeding replaces the current snapshot;
do not run the example seed over data you want to keep.

`make test` runs lint, unit tests and shell regressions. `make verify` exercises
PostgreSQL, checks deployed source/assets and runs desktop/mobile browser tests.
Database tests use temporary schemas, not the seeded catalogue schema.

## Changes

Keep backend and frontend behavior in their existing feature slices. Keep
orchestration in shell scripts behind Make commands. Add a regression that
exercises the actual seed or HTTP/UI path, not only an isolated helper.
Update directly related documentation.

Preserve unknown values, provenance, model identity, read-only serving APIs
and atomic snapshot replacement. Do not add network calls from the API or
browser to upstream model sources. Retain the plain, accessible interface
described in [DESIGN.md](DESIGN.md).

Never include credentials, deployment state, database dumps or real customer
data in a change. `.local/`, `.azure/` and environment files are not source
files. Use synthetic fixtures and redact logs before posting them.

Keep commits focused, explain behavioral changes in the pull request, and
state which checks you ran. By contributing, you agree that your contributions
are licensed under the project's [MIT license](LICENSE). Submit only work you
have permission to contribute.

Be respectful and focus feedback on the work. Report security issues through
the process in [SECURITY.md](SECURITY.md), not in a public bug report.
