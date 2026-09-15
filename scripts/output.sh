#!/bin/sh
set -eu
bold=
reset=
if [ -t 1 ] && [ -z "${NO_COLOR+x}" ]; then
    bold=$(printf '\033[1m')
    reset=$(printf '\033[0m')
fi
section() { printf '\n%s=== %s ===%s\n\n' "$bold" "$1" "$reset"; }
row() { printf '  %s%-22s%s %s\n' "$bold" "$1" "$reset" "$2"; }

case "${1:-}" in
    section) section "$2";;
    help)
        section "Local dashboard"
        row "make up" "Build images and start or update the owned kind cluster"
        row "make seed" "Import models.dev and optional Azure metadata into PostgreSQL"
        row "make logs" "Show recent application logs"
        section "Development and verification"
        row "make test" "Check shell guards, Python, TypeScript and unit tests"
        row "make verify" "Verify real PostgreSQL, deployed assets, cancellation and browser flows"
        row "make dev-ui" "Run Vite against the local cluster API"
        section "Azure Container Apps"
        row "make azure-deploy" "Validate and deploy the public dashboard with private data services"
        row "make azure-configure" "Apply app configuration using deployed images; do not rebuild or seed"
        row "make azure-seed" "Run a live metadata refresh in the private cloud database"
        row "make azure-status" "Show the cloud apps and their deployment state"
        row "make azure-verify" "Check cloud images, ingress, live data and browser flows"
        section "Teardown"
        row "make down" "Delete the owned kind cluster and its local database"
        printf '\n  Prerequisites: Docker with Linux containers, kind, kubectl, sh, curl, jq, OpenSSL, nc and uv.\n'
        printf '  Verification also uses Node/npm and shasum.\n'
        printf '\n  Configuration: ports.env\n  Documentation: README.md\n'
        printf '  Local dashboard: http://127.0.0.1:%s\n\n' "${UI_PORT:-18420}"
        ;;
    *) printf 'Unknown output command.\n' >&2; exit 1;;
esac
