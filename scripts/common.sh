#!/bin/sh
set -eu
umask 077
LC_ALL=C
export LC_ALL

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
LOCAL="$ROOT/.local"
CLUSTER=model-catalogue
NODE=model-catalogue-control-plane
NAMESPACE=model-catalogue
KUBECONFIG="$LOCAL/kubeconfig"
OWNER="$LOCAL/owner.json"
PASSWORD_FILE="$LOCAL/db-password"
API_IMAGE=model-catalogue-api:local
UI_IMAGE=model-catalogue-ui:local
export KUBECONFIG KIND_EXPERIMENTAL_PROVIDER=docker
cd "$ROOT"

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { for tool in "$@"; do command -v "$tool" >/dev/null 2>&1 || die "Missing $tool; see README prerequisites."; done; }
k() { kubectl --kubeconfig "$KUBECONFIG" --context "kind-$CLUSTER" --namespace "$NAMESPACE" "$@"; }
d() { docker --context "$DOCKER_CONTEXT" "$@"; }

need docker jq
: "${UI_PORT:?Run this script through make}"
: "${DB_PORT:?Run this script through make}"
: "${VITE_PORT:?Run this script through make}"
: "${API_PORT:?Run this script through make}"
for port in "$UI_PORT" "$DB_PORT" "$VITE_PORT"; do
    case "$port" in ''|0*|*[!0-9]*) die "Host ports must be decimal integers without leading zeros.";; esac
    [ "$port" -ge 10240 ] && [ "$port" -le 65535 ] || die "Choose host ports from 10240 through 65535."
done
[ "$UI_PORT" != "$DB_PORT" ] && [ "$UI_PORT" != "$VITE_PORT" ] && [ "$DB_PORT" != "$VITE_PORT" ] || die "Host ports must be distinct."
[ "$API_PORT" = 18421 ] || die "API_PORT is the fixed internal port 18421."

if [ -f "$OWNER" ]; then
    DOCKER_CONTEXT=$(jq -er '.docker_context | strings | select(length > 0)' "$OWNER") || die "Invalid ownership record."
else
    DOCKER_CONTEXT=$(docker context show) || die "Cannot identify the Docker context."
fi
export DOCKER_CONTEXT

docker_ready() {
    container_os=$(d info --format '{{.OSType}}') || die "Start Docker and retry."
    [ "$container_os" = linux ] || die "This workflow requires Docker running Linux containers."
}

node_id() { d ps -aq --no-trunc --filter "name=^/$NODE\$"; }

node_metadata() {
    d inspect "$NODE" --format '{"id":{{json .Id}},"name":{{json .Name}},"cluster":{{json (index .Config.Labels "io.x-k8s.kind.cluster")}},"ports":{{json .NetworkSettings.Ports}}}'
}

check_owner() {
    [ -f "$OWNER" ] || die "A same-named cluster exists without an ownership record; refusing to use it."
    metadata=$(node_metadata) || die "Cannot inspect the recorded cluster."
    printf '%s' "$metadata" | jq -e --slurpfile owner "$OWNER" \
        --arg node "/$NODE" --arg cluster "$CLUSTER" --arg root "$ROOT" '
        .id == $owner[0].container_id and .name == $node and .cluster == $cluster
        and $owner[0].project_root == $root
        ' >/dev/null || die "Cluster identity does not match. No resources were changed."
}

check_network() {
    metadata=$(node_metadata) || die "Cannot inspect the cluster mappings."
    printf '%s' "$metadata" | jq -e --slurpfile owner "$OWNER" '
        .ports["30420/tcp"][0].HostIp == "127.0.0.1"
        and .ports["30420/tcp"][0].HostPort == ($owner[0].ui_port | tostring)
        and .ports["6443/tcp"][0].HostIp == "127.0.0.1"
        and ("https://127.0.0.1:" + .ports["6443/tcp"][0].HostPort) == $owner[0].api_server
        ' >/dev/null || die "Recorded network mappings do not match. Recreate the owned cluster with make down and make up."
}

check_kubeconfig() {
    [ -f "$KUBECONFIG" ] || die "The project kubeconfig is missing."
    configured_server=$(k config view --minify -o jsonpath='{.clusters[0].cluster.server}') || die "Cannot read project kubeconfig."
    recorded_server=$(jq -er '.api_server' "$OWNER") || die "Invalid recorded API server."
    [ "$configured_server" = "$recorded_server" ] || die "Kubeconfig does not belong to the recorded Docker cluster."
}

check_host_mapping() {
    recorded_port=$(jq -er '.ui_port' "$OWNER") || die "Invalid recorded UI port."
    [ "$recorded_port" = "$UI_PORT" ] || die "UI_PORT changed. Run make down, then make up to recreate the owned cluster."
}

require_cluster() {
    docker_ready
    current_id=$(node_id) || die "Cannot list Docker containers."
    [ -n "$current_id" ] || die "No local cluster; run make up first."
    check_owner
    check_network
    check_kubeconfig
    check_host_mapping
    k get namespace "$NAMESPACE" >/dev/null
}

validate_password() {
    [ -f "$PASSWORD_FILE" ] || die "Database password file is missing. Do not regenerate it for an existing database."
    password_value=$(cat "$PASSWORD_FILE") || die "Cannot read database password."
    case "$password_value" in ''|*[!A-Za-z0-9_-]*) die "Password file must contain only URL-safe characters, without whitespace.";; esac
    file_size=$(wc -c < "$PASSWORD_FILE" | tr -d '[:space:]')
    [ "$file_size" -ge 40 ] && [ "$file_size" -le 128 ] || die "Invalid password file length."
    [ "$file_size" -eq "${#password_value}" ] || die "Password file contains trailing whitespace."
}

check_credentials() {
    validate_password
    secret_json=$(k get secret postgres --ignore-not-found -o json) || die "Cannot inspect database credentials."
    if [ -n "$secret_json" ]; then
        remote_password=$(printf '%s' "$secret_json" | jq -er '.data.password') || die "Database Secret is missing its password."
        local_password=$(openssl base64 -A < "$PASSWORD_FILE") || die "Cannot encode local credentials."
        [ "$remote_password" = "$local_password" ] || die "Local credentials differ from the database Secret; refusing to overwrite them."
    else
        existing_volume=$(k get pvc data-postgres-0 --ignore-not-found -o name) || die "Cannot inspect database storage."
        [ -z "$existing_volume" ] || die "A database volume exists without its Secret; restore credentials before continuing."
    fi
}

save_owner() {
    metadata=$(node_metadata) || die "Cannot record the new cluster."
    server=$(k config view --minify -o jsonpath='{.clusters[0].cluster.server}') || die "Cannot record the API server."
    printf '%s' "$metadata" | jq --arg context "$DOCKER_CONTEXT" --arg root "$ROOT" \
        --arg server "$server" --argjson port "$UI_PORT" \
        '{container_id: .id, docker_context: $context, project_root: $root, api_server: $server, ui_port: $port}' > "$OWNER"
    check_owner
    check_network
    check_kubeconfig
}

api_get() { curl --fail --silent --show-error --max-time 30 "http://127.0.0.1:$UI_PORT$1"; }
